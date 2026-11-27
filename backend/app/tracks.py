"""Rota da faixa individual: dados do Spotify + BPM, áudio e selo do Deezer."""
import asyncio
import logging
import time

import httpx
from fastapi import APIRouter, HTTPException, Request

from . import enrichment_store, evidence_store, labels, subgenre, taxonomy
from .auth import get_valid_access_token
from .cache import track_detail_cache
from .deezer_client import (
    NaoConfere,
    buscar_faixa,
    get_label_for_track,
    get_preview_url,
)
from .lastfm_client import NoAnswer, get_artist_tags, get_track_tags
from .models import LabelRef, SearchHit, SubgenreShare, TrackDetail
from .playlists import _spotify_error, account_track_ids
from .spotify_client import SpotifyClient
from .vector_store import similar_to_track

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tracks", tags=["tracks"])


async def build_track_detail(access_token: str, track_id: str) -> TrackDetail:
    """Monta o detalhe de uma faixa — usado pela rota HTTP e pelo chat.

    Uma faixa custa três chamadas externas (Spotify, Last.fm x2, Deezer) e os
    metadados não são por usuário, então o resultado é cacheado por id. Em
    desenvolvimento isso importa mais do que parece: o `StrictMode` do React
    monta cada efeito duas vezes, e sem o cache toda visita à página da faixa
    batia duas vezes no Spotify.
    """
    cached = track_detail_cache.get(track_id)
    if cached is not None:
        return cached

    async with httpx.AsyncClient(timeout=20.0) as client:
        # Faixa que já passou por uma análise de playlist tem os metadados no
        # banco: abrir a página dela não custa nada no Spotify.
        faixa = await asyncio.to_thread(enrichment_store.get_spotify_track, track_id)
        if faixa is None:
            # Pelo SpotifyClient, que respeita o bloqueio; por fora dele esta rota
            # continuava chamando o Spotify durante um bloqueio.
            faixa = _campos_usados(await SpotifyClient(access_token).get_track(client, track_id))
            await asyncio.to_thread(enrichment_store.put_spotify_tracks, [faixa])
        artistas = [a["name"] for a in (faixa.get("artists") or []) if a and a.get("name")]
        nome = faixa.get("name") or "(sem título)"
        principal = artistas[0] if artistas else ""

        deezer, tags, artist_tags = await _buscar_em_paralelo(
            client, principal, nome, faixa.get("duration_ms")
        )

        guardada = await _evidencia_guardada(track_id)
        selo, selo_novo, selo_falhou = await _selo(
            client, guardada, deezer, (principal, nome, faixa.get("duration_ms"))
        )

    album = faixa.get("album") or {}
    imagens = album.get("images") or []

    # A mesma classificação da análise de playlist, para a página da faixa
    # mostrar o gênero com confiança e não só uma nuvem de tags.
    classificacao = taxonomy.classify(artist_tags=artist_tags, track_tags=tags)

    # O BPM guardado por uma análise anterior vale quando o Deezer não deu o seu.
    bpm = (deezer or {}).get("bpm")
    if bpm is None and guardada is not None:
        bpm = guardada.bpm
    mistura = labels.blend_with_label(
        classificacao.genre, artist_tags=artist_tags, track_tags=tags, bpm=bpm, label=selo
    )

    detail = TrackDetail(
        track_id=faixa.get("id", track_id),
        name=nome,
        artists=artistas,
        album=album.get("name"),
        image=imagens[0]["url"] if imagens else None,
        duration_ms=faixa.get("duration_ms") or 0,
        spotify_url=(faixa.get("external_urls") or {}).get("spotify"),
        # A interface mostra texto; o peso serviu para classificar e fica aqui.
        # As tags descartadas de propósito (país, "seen live") não chegam à tela.
        tags=[t.name for t in tags if not taxonomy.load().discarded(t.name)],
        artist_tags=[t.name for t in artist_tags if not taxonomy.load().discarded(t.name)],
        genre=classificacao.genre,
        subgenre=mistura.subgenre,
        genre_confidence=classificacao.confidence or None,
        genre_evidence=classificacao.evidence,
        **subgenre.subgenre_fields(mistura),
        subgenre_reference=_referencia(mistura.lean),
        label=selo or None,
        label_info=_selo_no_mapa(selo),
        bpm=bpm,
        preview_url=(deezer or {}).get("preview_url"),
        deezer_url=(deezer or {}).get("deezer_url"),
        match_confidence=(deezer or {}).get("confianca"),
        matched_title=(deezer or {}).get("titulo_encontrado"),
    )
    # Selo que falhou por agora (rede, cota) não fica na memória: a próxima
    # visita tenta de novo em vez de mostrar a faixa sem selo por horas.
    if not selo_falhou:
        track_detail_cache[track_id] = detail
    await _guardar_evidencia(faixa.get("id", track_id), len(artistas), artist_tags, tags, deezer, selo_novo)
    return detail


def _deezer_alta(deezer) -> bool:
    """Só um match de confiança `alta` vira evidência: um aproximado pode ser
    outra gravação (e outro lançamento, com outro selo)."""
    return bool(deezer) and deezer.get("confianca") == "alta" and deezer.get("deezer_id") is not None


async def _selo(client, guardada, deezer, conferir) -> tuple[str | None, dict | None, bool]:
    """O selo da faixa, o que guardar dele (None = nada novo) e se a busca falhou.

    O selo vale para um `deezer_id`: o do match `alta` de agora ou, sem ele, o
    guardado. Já consultado para esse mesmo id → o guardado, sem rede. Senão
    pede o selo desta faixa só. O id guardado pode ter vindo de um match
    aproximado (a análise de playlist aceita), então vai com `conferir` (a
    faixa do Deezer precisa passar na regra `alta`); o de agora já passou, e
    leva o álbum que `buscar_faixa` leu. Falha (None) não é guardada: a próxima
    visita ou o job perguntam de novo. "" é resposta (o álbum não tem selo); não
    conferir também (guardado como selo None, consultado).
    """
    alta = _deezer_alta(deezer)
    deezer_id = deezer["deezer_id"] if alta else (guardada.deezer_id if guardada else None)
    if guardada is not None and guardada.label_checked_at is not None:
        mesma_origem = deezer_id is None or guardada.label_deezer_id == deezer_id
        # "Não conferiu" guardado cede a um match `alta` desta visita.
        if mesma_origem and not (alta and guardada.label is None):
            return guardada.label, None, False
    if deezer_id is None:
        return (guardada.label if guardada else None), None, False
    try:
        selo = await get_label_for_track(
            client,
            deezer_id,
            conferir=None if alta else conferir,
            album_id=deezer.get("album_id") if alta else None,
        )
    except Exception:
        logger.exception("Não consegui buscar o selo de %s no Deezer", deezer_id)
        selo = None
    if selo is None:
        return None, None, True
    if isinstance(selo, NaoConfere):
        selo = None
    return selo, {"label": selo, "label_checked_at": time.time(), "label_deezer_id": deezer_id}, False


def _selo_no_mapa(selo: str | None) -> LabelRef | None:
    info = labels.lookup(selo)
    if info is None:
        return None
    fatias = sorted(info.shares.items(), key=lambda item: (-item[1], item[0]))
    return LabelRef(
        name=info.name,
        nota=info.nota,
        fonte=info.fonte,
        shares=[SubgenreShare(label=sub, share=round(share, 3)) for sub, share in fatias],
    )


def _referencia(lean: str | None) -> dict | None:
    info = taxonomy.subgenre_info(lean) if lean else None
    if info is None:
        return None
    return {"name": info.name, "bpm": list(info.bpm) if info.bpm else None, "about": info.about, "source": info.source}


async def _evidencia_guardada(track_id: str):
    try:
        return (await asyncio.to_thread(evidence_store.get_many, [track_id])).get(track_id)
    except Exception:
        logger.exception("Não consegui ler a evidência de %s", track_id)
        return None


async def _guardar_evidencia(
    track_id: str, n_artistas: int, artist_tags, tags, deezer, selo: dict | None = None
) -> None:
    """Só o que respondeu. Daqui só se conhecem as tags do artista principal, então
    numa faixa com mais artistas elas não substituem a lista combinada que a análise
    da playlist guarda. O Deezer devolve None tanto para "não achou" quanto para
    falha, então só um match conta como consultado — e só o de confiança `alta`:
    um aproximado pode ser outra gravação, e o BPM dele ficaria como evidência
    permanente. Fora isso, os campos do Deezer não são tocados. `selo` são os
    campos do selo que acabou de ser buscado (None = nada novo)."""
    alta = _deezer_alta(deezer)
    ev = evidence_store.TrackEvidence(
        track_id=track_id,
        artist_tags=None if isinstance(artist_tags, NoAnswer) or n_artistas != 1 else artist_tags,
        track_tags=None if isinstance(tags, NoAnswer) else tags,
        bpm=deezer.get("bpm") if alta else None,
        deezer_id=deezer["deezer_id"] if alta else None,
        deezer_checked_at=time.time() if alta else None,
        **(selo or {}),
    )
    try:
        await asyncio.to_thread(evidence_store.put, ev)
    except Exception:
        logger.exception("Não consegui guardar a evidência de %s", track_id)


def _campos_usados(faixa: dict) -> dict:
    """Só o que o app lê do objeto de faixa — o mesmo recorte que a listagem de
    faixas de playlist pede ao Spotify, para as duas origens guardarem igual."""
    album = faixa.get("album") or {}
    return {
        "id": faixa.get("id"),
        "name": faixa.get("name"),
        "duration_ms": faixa.get("duration_ms"),
        "popularity": faixa.get("popularity"),
        "explicit": faixa.get("explicit"),
        "external_urls": faixa.get("external_urls"),
        "album": {k: album.get(k) for k in ("name", "images", "release_date")},
        "artists": [{"id": a.get("id"), "name": a.get("name")} for a in faixa.get("artists") or [] if a],
    }


@router.get("/preview/{deezer_id}")
async def track_preview(deezer_id: int, request: Request):
    """A URL atual da prévia de 30s no Deezer.

    As análises guardadas não levam a prévia: ela é uma URL assinada que expira
    em minutos. O player pede esta rota na hora do play, com o id do Deezer que
    a faixa guarda."""
    await get_valid_access_token(request)
    async with httpx.AsyncClient(timeout=15.0) as client:
        url = await get_preview_url(client, deezer_id)
    if not url:
        raise HTTPException(status_code=404, detail="Esta faixa não tem prévia no Deezer.")
    return {"preview_url": url}


@router.get("/{track_id}", response_model=TrackDetail)
async def track_detail(track_id: str, request: Request):
    """Tudo que a página da faixa precisa, resolvido a partir do id do Spotify."""
    token = await get_valid_access_token(request)
    try:
        return await build_track_detail(token, track_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Faixa não encontrada") from exc
        raise _spotify_error(exc) from exc


@router.get("/{track_id}/similar", response_model=list[SearchHit])
async def track_similar(track_id: str, request: Request, limit: int = 8):
    """Faixas parecidas com esta, dentro do que já foi indexado.

    Devolve lista vazia se a faixa ainda não entrou no índice — o índice só
    cresce quando você analisa a playlist que a contém.
    """
    await get_valid_access_token(request)
    # Só entre as faixas desta conta: o índice é compartilhado entre contas.
    return await similar_to_track(track_id, limite=limit, track_ids=await account_track_ids(request))


async def _buscar_em_paralelo(client, artista: str, titulo: str, duracao_ms):
    deezer, tags, artist_tags = await asyncio.gather(
        buscar_faixa(client, artista, titulo, duracao_ms),
        get_track_tags(client, artista, titulo),
        get_artist_tags(client, artista),
        return_exceptions=True,
    )
    return (
        deezer if isinstance(deezer, dict) else None,
        tags if isinstance(tags, list) else NoAnswer(),
        artist_tags if isinstance(artist_tags, list) else NoAnswer(),
    )
