"""Combines Last.fm artist tags (broad genre) + Last.fm track tags (subgenre) into
per-track genre info, then aggregates it into playlist-level distributions.

Spotify supplies the playlist and its tracks; the genre data all comes from Last.fm
since Spotify removed the `genres` field from artist objects in its 2026 API changes.
"""
import asyncio
import logging
import time
from collections import Counter

import httpx

from . import analysis_store, enrichment_store, evidence_store, profile_store, subgenre, taxonomy
from .cache import playlist_analysis_cache
from .deezer_client import get_many as get_deezer_many
from .lastfm_client import NoAnswer, get_artist_tags, get_track_tags
from .models import GenreCount, PlaylistAnalysis, PlaylistSummary, TrackGenreInfo
from .spotify_client import SpotifyClient, gather_with_concurrency

logger = logging.getLogger(__name__)

# One Last.fm request per track and per artist, so concurrency sets the wall time.
# Measured against the live API with 60 lookups: 8 -> 1.69s, 16 -> 1.22s, 24 -> 1.08s,
# 32 -> 0.74s, with zero 429s throughout. 24 takes most of the win while leaving
# headroom; a throttled lookup degrades to "no tags" rather than failing the request.
LASTFM_CONCURRENCY = 24

# The default keepalive pool (20) would throttle the two pools above; size it to fit
# both the artist and the track pass running at once.
HTTP_LIMITS = httpx.Limits(max_connections=64, max_keepalive_connections=64)


# Análises em andamento, por (playlist, com_audio). A varredura da busca, a do
# perfil e a própria página podem pedir a mesma playlist ao mesmo tempo; sem
# isto cada uma repetiria as chamadas ao Spotify.
_in_flight: dict[tuple[str, bool], asyncio.Task] = {}


async def build_playlist_analysis(
    access_token: str, playlist_id: str, *, include_audio: bool = True, trust_cache: bool = True
) -> PlaylistAnalysis:
    """Análise completa da playlist, lida do Spotify.

    `include_audio=False` pula o Deezer (BPM e prévia). É o modo da varredura do
    perfil: o Deezer aceita ~10 requisições por segundo e custa até duas por
    faixa, então numa conta inteira ele sozinho levaria minutos, enquanto o
    resto termina em segundos. Uma análise sem áudio nunca entra no
    `playlist_analysis_cache`, para a página da playlist não receber BPM vazio.

    `trust_cache=False` ignora o cache em memória e as análises em voo, e vai
    ao Spotify. É o que se usa quando ainda não se sabe se quem pede pode ver
    esta playlist: o 403 do Spotify é a checagem de permissão, e um resultado
    guardado para outra conta passaria por cima dela. Esta função não lê o
    banco — quem serve análise guardada é `playlists.analysis_for_user`, que
    confere a listagem da conta antes.
    """
    if trust_cache:
        cached = playlist_analysis_cache.get(playlist_id)
        if cached is not None:
            return cached

        # Uma análise completa já em voo serve também a quem não precisa de áudio.
        keys = [(playlist_id, True)] if include_audio else [(playlist_id, False), (playlist_id, True)]
        for key in keys:
            task = _in_flight.get(key)
            if task is not None:
                return await asyncio.shield(task)

    if not trust_cache:
        return await _build(access_token, playlist_id, include_audio)

    key = (playlist_id, include_audio)
    task = asyncio.create_task(_build(access_token, playlist_id, include_audio))
    _in_flight[key] = task
    task.add_done_callback(lambda t: _forget(key, t))
    return await asyncio.shield(task)


def _forget(key, task: asyncio.Task) -> None:
    _in_flight.pop(key, None)
    # Se quem pediu desistiu (página fechada), ninguém lê o erro; lê-lo aqui
    # evita o aviso de "exception was never retrieved".
    if not task.cancelled():
        task.exception()


async def _build(access_token: str, playlist_id: str, include_audio: bool) -> PlaylistAnalysis:
    spotify = SpotifyClient(access_token)

    async with httpx.AsyncClient(timeout=20.0, limits=HTTP_LIMITS) as client:
        spotify_started = time.perf_counter()
        playlist_data, tracks = await asyncio.gather(
            spotify.get_playlist(client, playlist_id),
            spotify.get_all_playlist_tracks(client, playlist_id),
        )
        spotify_seconds = time.perf_counter() - spotify_started

        # Last.fm is keyed by name, not by Spotify id.
        artist_names = sorted(
            {a["name"] for t in tracks for a in (t.get("artists") or []) if a and a.get("name")}
        )

        async def genre_for(artist_name: str) -> tuple[str, list[str]]:
            return artist_name, await get_artist_tags(client, artist_name)

        async def tags_for(track: dict) -> list[str]:
            primary_artist = ((track.get("artists") or [{}])[0] or {}).get("name") or ""
            return await get_track_tags(client, primary_artist, track.get("name") or "")

        # Deezer roda junto com o Last.fm: são serviços diferentes, então uma
        # espera não precisa custar a outra.
        deezer_pairs = [
            (((t.get("artists") or [{}])[0] or {}).get("name") or "", t.get("name") or "")
            for t in tracks
        ]

        async def no_audio() -> list[dict]:
            return [{"deezer_id": None, "bpm": None, "preview_url": None, "deezer_url": None} for _ in tracks]

        lastfm_started = time.perf_counter()
        artist_genre_pairs, all_tags, all_deezer = await asyncio.gather(
            gather_with_concurrency(LASTFM_CONCURRENCY, *(genre_for(n) for n in artist_names)),
            gather_with_concurrency(LASTFM_CONCURRENCY, *(tags_for(t) for t in tracks)),
            get_deezer_many(client, deezer_pairs) if include_audio else no_audio(),
        )
        artist_genres = dict(artist_genre_pairs)
        lastfm_seconds = time.perf_counter() - lastfm_started

    logger.info(
        "Analysed %s: %d tracks / %d artists — Spotify %.2fs, Last.fm+Deezer %.2fs",
        playlist_id, len(tracks), len(artist_names), spotify_seconds, lastfm_seconds,
    )

    # BPM de uma enriquecida anterior serve quando o Deezer não deu o seu agora.
    stored_evidence = await _stored_evidence([t["id"] for t in tracks])
    artists_without_answer = {n for n, tags in artist_genres.items() if isinstance(tags, NoAnswer)}
    evidence_to_store: list[evidence_store.TrackEvidence] = []

    track_infos: list[TrackGenreInfo] = []
    bars: dict[str, list[float]] = {}  # rótulo -> [confiante, incerta]
    genre_counter: Counter = Counter()
    subgenre_counter: Counter = Counter()
    artist_counter: Counter = Counter()
    missing_genre = 0

    for track, lastfm_tags, deezer in zip(tracks, all_tags, all_deezer):
        track_artist_names = [
            a["name"] for a in (track.get("artists") or []) if a and a.get("name")
        ]
        # Tags de todos os artistas creditados, com peso. A mesma tag vinda de
        # dois artistas soma — numa colaboração, isso é o que se quer.
        artist_tags: list[taxonomy.Tag] = []
        for name in track_artist_names:
            artist_tags.extend(taxonomy.as_tags(artist_genres.get(name, [])))

        classification = taxonomy.classify(artist_tags=artist_tags, track_tags=lastfm_tags)
        subgenre_tags = _display_tags(lastfm_tags, artist_tags)

        if classification.genre is None:
            missing_genre += 1
        else:
            # UM voto por faixa, no gênero classificado. Antes cada tag contava
            # um voto: uma faixa com três artistas deixava até nove, e "rock"
            # liderava por ser contado junto com "classic rock" e "hard rock".
            genre_counter[classification.genre] += 1

        for name in track_artist_names:
            artist_counter[name] += 1

        bpm = deezer["bpm"]
        if bpm is None and track["id"] in stored_evidence:
            bpm = stored_evidence[track["id"]].bpm
        result = subgenre.blend(
            classification.genre, artist_tags=artist_tags, track_tags=taxonomy.as_tags(lastfm_tags), bpm=bpm
        )
        if result.lean:
            subgenre_counter[result.lean] += 1
        subgenre.add_to_bars(bars, result.blend, result.unsure)
        evidence_to_store.append(
            _evidence_of(track, track_artist_names, artists_without_answer, artist_tags, lastfm_tags, deezer, include_audio)
        )

        album = track.get("album") or {}
        images = album.get("images") or []
        urls = track.get("external_urls") or {}

        track_infos.append(
            TrackGenreInfo(
                track_id=track["id"],
                name=track.get("name") or "(sem título)",
                artists=track_artist_names,
                album=album.get("name"),
                image=images[0]["url"] if images else None,
                duration_ms=track.get("duration_ms") or 0,
                popularity=track.get("popularity"),
                genres=classification.genres,
                subgenre_tags=subgenre_tags,
                genre=classification.genre,
                subgenre=result.subgenre,
                genre_confidence=classification.confidence or None,
                genre_evidence=classification.evidence,
                **subgenre.subgenre_fields(result),
                bpm=deezer["bpm"],
                preview_url=deezer["preview_url"],
                deezer_url=deezer["deezer_url"],
                deezer_id=deezer.get("deezer_id"),
                spotify_url=urls.get("spotify"),
                added_at=track.get("added_at"),
                release_year=_release_year(album.get("release_date")),
                explicit=track.get("explicit"),
            )
        )

    playlist_images = playlist_data.get("images") or []
    summary = PlaylistSummary(
        id=playlist_data["id"],
        name=playlist_data.get("name") or "Sem nome",
        description=playlist_data.get("description") or None,
        image=playlist_images[0]["url"] if playlist_images else None,
        track_count=len(track_infos),
        owner=(playlist_data.get("owner") or {}).get("display_name"),
        snapshot_id=playlist_data.get("snapshot_id"),
    )

    # Os dois gráficos não se repetem mais por construção: `genre_counter` só
    # recebe rótulo de gênero da taxonomia e `subgenre_counter` só rótulo de
    # subgênero, que são conjuntos disjuntos. A limpeza que existia aqui —
    # apagar do gráfico de subgêneros toda tag que também era gênero — era
    # remendo de contar strings livres, e saiu junto.

    def top_counts(counter: Counter, limit: int = 25) -> list[GenreCount]:
        return [GenreCount(label=label, count=count) for label, count in counter.most_common(limit)]

    analysis = PlaylistAnalysis(
        playlist=summary,
        tracks=track_infos,
        genre_distribution=top_counts(genre_counter),
        subgenre_distribution=top_counts(subgenre_counter),
        subgenre_bars=subgenre.bars_from(bars),
        top_artists=top_counts(artist_counter, limit=15),
        tracks_missing_genre=missing_genre,
        genre_taxonomy=taxonomy.load().version,
        **_bpm_fields(track_infos),
    )
    if include_audio:
        playlist_analysis_cache[playlist_id] = analysis

    await _persist(analysis, has_audio=include_audio, spotify_tracks=tracks)
    await _persist_evidence(evidence_to_store)
    return analysis


async def _stored_evidence(track_ids: list[str]) -> dict[str, evidence_store.TrackEvidence]:
    try:
        return await asyncio.to_thread(evidence_store.get_many, track_ids)
    except Exception:
        logger.exception("Não consegui ler a evidência guardada")
        return {}


def _evidence_of(
    track: dict,
    artist_names: list[str],
    artists_without_answer: set[str],
    artist_tags: list[taxonomy.Tag],
    lastfm_tags: list,
    deezer: dict,
    include_audio: bool,
) -> evidence_store.TrackEvidence:
    """O que desta faixa foi de fato respondido agora; o resto fica None.

    Falha do Last.fm chega como `NoAnswer` e não vira "sem tags". O Deezer não
    distingue "não achou" de "não respondeu" (ambos voltam vazios), então só um
    match marca a faixa como consultada."""
    artists_ok = bool(artist_names) and not any(n in artists_without_answer for n in artist_names)
    found = include_audio and deezer.get("deezer_id") is not None
    return evidence_store.TrackEvidence(
        track_id=track["id"],
        artist_tags=artist_tags if artists_ok else None,
        track_tags=None if isinstance(lastfm_tags, NoAnswer) else taxonomy.as_tags(lastfm_tags),
        bpm=deezer["bpm"] if found else None,
        deezer_id=deezer["deezer_id"] if found else None,
        deezer_checked_at=time.time() if found else None,
    )


async def _persist_evidence(items: list[evidence_store.TrackEvidence]) -> None:
    def save() -> None:
        for ev in items:
            evidence_store.put(ev)

    try:
        await asyncio.to_thread(save)
    except Exception:
        logger.exception("Não consegui guardar a evidência das faixas")


async def _persist(analysis: PlaylistAnalysis, *, has_audio: bool, spotify_tracks: list[dict] | None = None) -> None:
    """Toda análise fica guardada: a completa (página da playlist), o resumo
    (perfil) e os metadados das faixas (página da faixa). Inclusive as da
    varredura da busca, que assim adiantam o trabalho do resto de graça.

    Falhar aqui não derruba a análise que já foi feita para quem pediu."""

    def save() -> None:
        analysis_store.save(analysis, has_audio=has_audio)
        profile_store.save(analysis, has_audio=has_audio)
        if spotify_tracks:
            # `added_at` é da entrada na playlist, não da faixa.
            enrichment_store.put_spotify_tracks(
                [{k: v for k, v in t.items() if k != "added_at"} for t in spotify_tracks]
            )

    try:
        await asyncio.to_thread(save)
    except Exception:
        logger.exception("Não consegui guardar a análise de %s", analysis.playlist.id)


def _bpm_fields(track_infos: list[TrackGenreInfo]) -> dict:
    bpm_values = [t.bpm for t in track_infos if t.bpm is not None]
    return {
        "bpm_histogram": _bpm_histogram(bpm_values),
        "average_bpm": round(sum(bpm_values) / len(bpm_values), 1) if bpm_values else None,
        "tracks_missing_bpm": len(track_infos) - len(bpm_values),
    }


# Análises guardadas sem áudio sendo completadas agora, por playlist.
_audio_in_flight: dict[str, asyncio.Task] = {}


async def add_audio(analysis: PlaylistAnalysis) -> PlaylistAnalysis:
    """Completa com BPM e prévia uma análise que foi feita sem áudio.

    A varredura do perfil e da busca analisa sem Deezer. Quando uma dessas
    playlists é aberta, não há por que reler tudo no Spotify: as faixas e as
    tags já estão na análise guardada, e só falta o Deezer."""
    playlist_id = analysis.playlist.id
    task = _audio_in_flight.get(playlist_id)
    if task is None:
        task = asyncio.create_task(_add_audio(analysis))
        _audio_in_flight[playlist_id] = task
        task.add_done_callback(lambda t: _forget_audio(playlist_id, t))
    return await asyncio.shield(task)


def _forget_audio(playlist_id: str, task: asyncio.Task) -> None:
    _audio_in_flight.pop(playlist_id, None)
    if not task.cancelled():
        task.exception()


async def _add_audio(analysis: PlaylistAnalysis) -> PlaylistAnalysis:
    pairs = [((t.artists or [""])[0], t.name) for t in analysis.tracks]
    async with httpx.AsyncClient(timeout=20.0, limits=HTTP_LIMITS) as client:
        audio = await get_deezer_many(client, pairs)

    tracks = [
        t.model_copy(
            update={
                "bpm": a["bpm"],
                "preview_url": a["preview_url"],
                "deezer_url": a["deezer_url"],
                "deezer_id": a.get("deezer_id"),
            }
        )
        for t, a in zip(analysis.tracks, audio)
    ]
    completed = analysis.model_copy(update={"tracks": tracks, **_bpm_fields(tracks)})
    playlist_analysis_cache[analysis.playlist.id] = completed
    await _persist(completed, has_audio=True)
    return completed


# Tags por faixa que seguem para a tela, o agrupamento e a busca semântica.
# Mais que isto não cabe na tabela de faixas e só adiciona ruído ao TF-IDF.
MAX_DISPLAY_TAGS = 12


def _display_tags(*fontes: list[taxonomy.Tag]) -> list[str]:
    """As tags da faixa em texto, da mais forte para a mais fraca.

    Fica de fora só o que a taxonomia descarta de propósito (país, instrumento,
    "seen live"). Tag que ela ainda não conhece CONTINUA aqui: pode ser gênero
    de verdade faltando no YAML, e tanto o agrupamento por clima quanto a busca
    semântica aproveitam a palavra mesmo sem ela estar classificada.

    A ordem é por peso do Last.fm, não alfabética: a primeira tag é a que mais
    descreve a faixa, e é ela que aparece quando a tabela corta a lista.
    """
    tabela = taxonomy.load()
    melhor: dict[str, taxonomy.Tag] = {}
    for fonte in fontes:
        # `as_tags` aceita tag sem peso: é a forma que o banco guardava antes.
        for tag in taxonomy.as_tags(fonte or []):
            if tabela.discarded(tag.name):
                continue
            chave = tag.name.strip().lower()
            if not chave:
                continue
            atual = melhor.get(chave)
            if atual is None or tag.weight > atual.weight:
                melhor[chave] = tag
    ordenadas = sorted(melhor.values(), key=lambda t: (-t.weight, t.name.lower()))
    return [t.name for t in ordenadas[:MAX_DISPLAY_TAGS]]


def _release_year(release_date: str | None) -> int | None:
    """"1997", "1997-05" e "1997-05-21" são todos formatos válidos do Spotify."""
    try:
        year = int((release_date or "")[:4])
    except ValueError:
        return None
    # Álbuns sem data vêm como "0000".
    return year if year >= 1900 else None




# Faixas de 20 BPM: largas o bastante para não virar ruído numa playlist de 40
# músicas, estreitas o bastante para separar balada de dance.
BPM_BUCKETS = [(0, 80), (80, 100), (100, 120), (120, 140), (140, 160), (160, 180), (180, 10_000)]


def _bpm_histogram(values: list[float]) -> list[GenreCount]:
    """Contagem por faixa de BPM, em ordem crescente.

    Diferente das outras distribuições, esta NÃO é ordenada por contagem: BPM é
    uma escala contínua, e reordenar por frequência destruiria a leitura de
    "onde esta playlist se concentra".
    """
    if not values:
        return []

    counts = []
    for low, high in BPM_BUCKETS:
        n = sum(1 for v in values if low <= v < high)
        if low == 0:
            label = f"< {high}"
        elif high == 10_000:
            label = f"{low}+"
        else:
            label = f"{low}–{high - 1}"
        counts.append(GenreCount(label=label, count=n))

    # Corta as faixas vazias das pontas para o gráfico não começar e terminar
    # com barras zeradas, mantendo os buracos internos (que são informação).
    first = next((i for i, c in enumerate(counts) if c.count), 0)
    last = len(counts) - next((i for i, c in enumerate(reversed(counts)) if c.count), 0)
    return counts[first:last]
