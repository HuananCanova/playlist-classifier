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

from . import profile_store
from .cache import playlist_analysis_cache
from .deezer_client import get_many as get_deezer_many
from .lastfm_client import get_artist_tags, get_track_tags
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
    access_token: str, playlist_id: str, *, include_audio: bool = True
) -> PlaylistAnalysis:
    """Análise completa da playlist.

    `include_audio=False` pula o Deezer (BPM e prévia). É o modo da varredura do
    perfil: o Deezer aceita ~10 requisições por segundo e custa até duas por
    faixa, então numa conta inteira ele sozinho levaria minutos, enquanto o
    resto termina em segundos. Uma análise sem áudio nunca entra no
    `playlist_analysis_cache`, para a página da playlist não receber BPM vazio.
    """
    cached = playlist_analysis_cache.get(playlist_id)
    if cached is not None:
        return cached

    # Uma análise completa já em voo serve também a quem não precisa de áudio.
    keys = [(playlist_id, True)] if include_audio else [(playlist_id, False), (playlist_id, True)]
    for key in keys:
        task = _in_flight.get(key)
        if task is not None:
            return await asyncio.shield(task)

    key = (playlist_id, include_audio)
    task = asyncio.create_task(_build(access_token, playlist_id, include_audio))
    _in_flight[key] = task
    task.add_done_callback(lambda t: _forget(key, t))
    return await asyncio.shield(task)


def _forget(key: tuple[str, bool], task: asyncio.Task) -> None:
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
            return [{"bpm": None, "preview_url": None, "deezer_url": None} for _ in tracks]

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

    track_infos: list[TrackGenreInfo] = []
    genre_counter: Counter = Counter()
    subgenre_counter: Counter = Counter()
    artist_counter: Counter = Counter()
    missing_genre = 0
    bpm_values: list[float] = []

    for track, lastfm_tags, deezer in zip(tracks, all_tags, all_deezer):
        track_artist_names = [
            a["name"] for a in (track.get("artists") or []) if a and a.get("name")
        ]
        track_genres: list[str] = []
        for name in track_artist_names:
            track_genres.extend(artist_genres.get(name, []))
        track_genres = sorted(set(track_genres))

        subgenre_tags = sorted(set(lastfm_tags) | set(track_genres))

        if not track_genres and not lastfm_tags:
            missing_genre += 1

        for g in track_genres:
            genre_counter[g] += 1
        for t in subgenre_tags:
            subgenre_counter[t] += 1
        for name in track_artist_names:
            artist_counter[name] += 1

        if deezer["bpm"] is not None:
            bpm_values.append(deezer["bpm"])

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
                genres=track_genres,
                subgenre_tags=subgenre_tags,
                bpm=deezer["bpm"],
                preview_url=deezer["preview_url"],
                deezer_url=deezer["deezer_url"],
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

    # A distribuição de subgêneros mostra só o que a de gêneros não mostra: uma tag
    # que já é gênero de algum artista da playlist ficaria repetida nos dois
    # gráficos. As tags de cada faixa seguem completas (agrupamento e busca usam).
    genre_keys = {g.lower() for g in genre_counter}
    for tag in [t for t in subgenre_counter if t.lower() in genre_keys]:
        del subgenre_counter[tag]

    def top_counts(counter: Counter, limit: int = 25) -> list[GenreCount]:
        return [GenreCount(label=label, count=count) for label, count in counter.most_common(limit)]

    analysis = PlaylistAnalysis(
        playlist=summary,
        tracks=track_infos,
        genre_distribution=top_counts(genre_counter),
        subgenre_distribution=top_counts(subgenre_counter),
        top_artists=top_counts(artist_counter, limit=15),
        bpm_histogram=_bpm_histogram(bpm_values),
        average_bpm=round(sum(bpm_values) / len(bpm_values), 1) if bpm_values else None,
        tracks_missing_genre=missing_genre,
        tracks_missing_bpm=len(track_infos) - len(bpm_values),
    )
    if include_audio:
        playlist_analysis_cache[playlist_id] = analysis

    # Toda análise vira resumo em disco para o perfil — inclusive as da página e
    # da varredura da busca, que assim adiantam o trabalho do perfil de graça.
    try:
        await asyncio.to_thread(profile_store.save, analysis, has_audio=include_audio)
    except Exception:
        logger.exception("Não consegui guardar o resumo de %s", playlist_id)
    return analysis


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
