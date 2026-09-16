"""Rota do artista: identidade no Spotify, contexto no Last.fm, presença no acervo.

Três fontes, uma página:

* **Spotify** (`/artists/{id}`) — foto e link, e só. Depois da migração de
  2026 o objeto do artista devolve apenas `id`, `name`, `images`,
  `external_urls`, `href`, `type` e `uri`: não há mais `followers`,
  `popularity` nem `genres`. É a identidade, porque o id vem das próprias
  faixas da playlist e não de uma busca por nome.
* **Last.fm** (`artist.getInfo`) — biografia, audiência, tags e parecidos. É o
  contexto que o Spotify parou de dar quando removeu `genres` do artista.
* **Deezer** (`/artist/{id}/top`) — as mais tocadas, com capa e prévia. O
  equivalente no Spotify (`/artists/{id}/top-tracks`) responde 403 para apps
  criados depois de 27/11/2024, a mesma migração que levou `audio-features`.
* **Acervo em disco** (`profile_store`) — em que playlists suas o artista
  aparece e com quais faixas. Não custa nenhuma chamada externa.

Só o Spotify é obrigatório, e apenas pelo nome: se o Last.fm ou o Deezer não
conhecem o artista, a seção correspondente some e o resto da página fica de pé.
"""
import asyncio
import logging
import time

import httpx
from fastapi import APIRouter, HTTPException, Request

from . import profile_store
from .auth import get_valid_access_token
from .cache import artist_profile_cache
from .deezer_client import get_artist_top
from .lastfm_client import get_artist_info
from .models import ArtistProfile, ArtistTrack, PlaylistSummary, SimilarArtist
from .playlists import _spotify_error, get_playlist_summaries
from .spotify_client import SpotifyClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/artists", tags=["artists"])

# Teto de faixas do acervo listadas na página. Um artista com 60 faixas suas
# viraria uma lista sem fim; o total continua no `library_track_count`.
MAX_LIBRARY_TRACKS = 60


# ── Índice reverso do acervo ────────────────────────────────────────────
#
# Varrer os resumos de 100+ playlists a cada abertura de página do artista
# seria ler o disco inteiro para achar uma linha. Em vez disso, monta-se uma
# vez um índice `id do artista -> faixas`, refeito só quando o acervo muda.
#
# A assinatura é (quantidade de arquivos, mtime mais recente): gravar um resumo
# novo ou reescrever um existente muda um dos dois, e ambos são baratos de ler.
_index: dict[str, list[dict]] | None = None
_index_signature: tuple[int, float] | None = None
_index_names: dict[str, str] = {}


def _store_signature() -> tuple[int, float]:
    try:
        files = list(profile_store.STORE_PATH.glob("*.json"))
    except OSError:
        return (0, 0.0)
    newest = max((f.stat().st_mtime for f in files), default=0.0)
    return (len(files), newest)


def _build_index() -> tuple[dict[str, list[dict]], dict[str, str]]:
    """`id do artista -> faixas dele no acervo`, lido dos resumos em disco."""
    by_artist: dict[str, list[dict]] = {}
    names: dict[str, str] = {}

    try:
        paths = sorted(profile_store.STORE_PATH.glob("*.json"))
    except OSError:
        return by_artist, names

    for path in paths:
        digest = profile_store.load(path.stem)
        if not digest:
            continue
        playlist = digest.get("playlist") or {}
        for track in digest.get("tracks") or []:
            # Resumos gravados antes deste campo existir não têm os ids; as
            # faixas deles ficam de fora em vez de derrubar a varredura.
            ids = track.get("artist_ids") or []
            track_names = track.get("artists") or []
            for position, artist_id in enumerate(ids):
                if not artist_id:
                    continue
                if position < len(track_names):
                    names.setdefault(artist_id, track_names[position])
                by_artist.setdefault(artist_id, []).append(
                    {
                        "track_id": track.get("id"),
                        "name": track.get("name"),
                        "image": track.get("image"),
                        "playlist_id": playlist.get("id"),
                        "playlist_name": playlist.get("name"),
                    }
                )
    return by_artist, names


def _library_index() -> tuple[dict[str, list[dict]], dict[str, str]]:
    global _index, _index_signature, _index_names
    signature = _store_signature()
    if _index is None or signature != _index_signature:
        started = time.perf_counter()
        _index, _index_names = _build_index()
        _index_signature = signature
        logger.info(
            "Índice de artistas do acervo: %d artistas de %d playlists em %.2fs",
            len(_index), signature[0], time.perf_counter() - started,
        )
    return _index, _index_names


def _deezer_track(track: dict) -> ArtistTrack:
    return ArtistTrack(
        name=track["title"],
        album=track.get("album"),
        image=track.get("image"),
        preview_url=track.get("preview_url"),
        deezer_url=track.get("deezer_url"),
    )


@router.get("/{artist_id}", response_model=ArtistProfile)
async def artist_profile(artist_id: str, request: Request):
    """A página do artista inteira, montada a partir do id do Spotify."""
    token = await get_valid_access_token(request)

    cached = artist_profile_cache.get(artist_id)
    if cached is not None:
        # O acervo é local e muda quando outra playlist é analisada; só ele é
        # refeito, para a parte cara (Spotify + Last.fm) continuar em cache.
        return await _with_library(cached, artist_id, request)

    spotify = SpotifyClient(token)
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            artist = await spotify.get_artist(client, artist_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise HTTPException(status_code=404, detail="Artista não encontrado") from exc
            raise _spotify_error(exc) from exc

        name = artist.get("name") or "(sem nome)"

        # As mais tocadas e o Last.fm são independentes: nenhuma espera pela
        # outra, e uma falha de qualquer uma não leva a página junto.
        #
        # As mais tocadas vêm do Deezer, não do Spotify: `/artists/{id}/
        # top-tracks` responde 403 para apps criados depois de 27/11/2024.
        top_raw, info = await asyncio.gather(
            get_artist_top(client, name),
            get_artist_info(client, name),
            return_exceptions=True,
        )

    if isinstance(top_raw, Exception):
        logger.warning("Sem as mais tocadas de %s: %s", name, top_raw)
        top_raw = []
    if isinstance(info, Exception):
        logger.warning("Sem o Last.fm de %s: %s", name, info)
        info = {}

    images = artist.get("images") or []
    profile = ArtistProfile(
        id=artist.get("id") or artist_id,
        name=name,
        image=images[0]["url"] if images else None,
        spotify_url=(artist.get("external_urls") or {}).get("spotify"),
        lastfm_url=info.get("url"),
        listeners=info.get("listeners"),
        playcount=info.get("playcount"),
        bio=info.get("bio"),
        tags=info.get("tags") or [],
        top_tracks=[_deezer_track(t) for t in top_raw if t and t.get("title")],
        similar=[
            SimilarArtist(name=s["name"], lastfm_url=s.get("url"))
            for s in (info.get("similar") or [])
        ],
    )

    artist_profile_cache[artist_id] = profile
    return await _with_library(profile, artist_id, request)


async def _with_library(profile: ArtistProfile, artist_id: str, request: Request) -> ArtistProfile:
    """Preenche a parte do acervo — tudo local, sem tocar em API externa."""
    index, names = await asyncio.to_thread(_library_index)
    rows = index.get(artist_id) or []

    # Nomes das playlists vêm da listagem (que já está em cache); o resumo em
    # disco também os tem, mas a listagem é a fonte viva e traz a capa.
    # Sem a listagem não dá para saber o que é do usuário; nesse caso a seção
    # vem vazia em vez de mostrar resumos de playlists não confirmadas.
    try:
        summaries = {p.id: p for p in await get_playlist_summaries(request)}
    except Exception:
        logger.warning("Sem a listagem de playlists: a seção do acervo fica vazia")
        summaries = {}

    # O índice cobre todos os resumos em disco, e os resumos são gravados por
    # playlist, não por conta. Só entram aqui as playlists que o Spotify acabou
    # de listar para quem está logado — a permissão continua vindo do Spotify,
    # e uma conta nunca vê o que outra analisou. Isso também corrige a contagem
    # para uma playlist que saiu da conta mas deixou o resumo para trás.
    seen_playlists: dict[str, PlaylistSummary] = {}
    tracks: list[ArtistTrack] = []
    owned = [r for r in rows if (r.get("playlist_id") or "") in summaries]

    for row in owned:
        playlist_id = row["playlist_id"]
        if playlist_id not in seen_playlists:
            seen_playlists[playlist_id] = summaries[playlist_id]
        if len(tracks) < MAX_LIBRARY_TRACKS:
            tracks.append(
                ArtistTrack(
                    track_id=row.get("track_id") or None,
                    name=row.get("name") or "(sem título)",
                    image=row.get("image"),
                    playlist_id=playlist_id,
                    playlist_name=summaries[playlist_id].name,
                )
            )

    # Um artista parecido que também está no seu acervo vira link interno; o
    # resto continua apontando para o Last.fm. Resolver o id pela busca do
    # Spotify custaria uma chamada por nome, e são até oito por página.
    by_name = {name.lower(): aid for aid, name in names.items()}
    similar = [
        s.model_copy(update={"spotify_id": by_name.get(s.name.lower())}) for s in profile.similar
    ]

    return profile.model_copy(
        update={
            "similar": similar,
            "library_tracks": tracks,
            "library_track_count": len(owned),
            "library_playlists": list(seen_playlists.values()),
            "library_scanned": bool(index),
        }
    )
