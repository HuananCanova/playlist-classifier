"""Resumos compactos de cada playlist, guardados em disco para o perfil.

O perfil agrega a conta inteira, e analisar dezenas de playlists do zero a cada
visita seria lento e caro no rate limit do Spotify. Então cada análise feita em
qualquer lugar do app (página da playlist, varredura da busca, varredura do
perfil) deixa aqui um resumo com só o que o perfil usa.

Um resumo vale enquanto o `snapshot_id` da playlist não muda — o Spotify troca
esse id a cada alteração de conteúdo, então ele responde exatamente "preciso
analisar de novo?". Sobrevive a reinícios do backend, ao contrário dos caches
em memória.

A chave é só o id da playlist, sem o usuário: o resumo descreve o conteúdo da
playlist, e o perfil só lê resumos das playlists que o próprio Spotify listou
para quem está logado. A permissão continua vindo do Spotify.
"""
import json
import logging
import os
import threading
import time
from pathlib import Path

from .models import PlaylistAnalysis

logger = logging.getLogger(__name__)

STORE_PATH = Path(__file__).resolve().parent.parent / ".profile_cache"

# Sobe quando o formato muda; resumos de outra versão são tratados como ausentes.
VERSION = 1

# Tags por faixa no resumo. As distribuições do perfil só olham o topo, e isso
# mantém um arquivo de playlist de 500 faixas na casa das centenas de KB.
MAX_TAGS_PER_TRACK = 8

_memo: dict[str, dict | None] = {}
_lock = threading.Lock()


def _path(playlist_id: str) -> Path:
    # Ids do Spotify são base62; o filtro só impede que um id estranho vire caminho.
    safe = "".join(c for c in playlist_id if c.isalnum())
    return STORE_PATH / f"{safe}.json"


def digest_from_analysis(analysis: PlaylistAnalysis, *, has_audio: bool) -> dict:
    p = analysis.playlist
    return {
        "version": VERSION,
        "snapshot_id": p.snapshot_id,
        "saved_at": time.time(),
        "has_audio": has_audio,
        "playlist": {
            "id": p.id,
            "name": p.name,
            "image": p.image,
            "track_count": p.track_count,
            "owner": p.owner,
        },
        "tracks": [
            {
                "id": t.track_id,
                "name": t.name,
                "artists": t.artists,
                "image": t.image,
                "duration_ms": t.duration_ms,
                "popularity": t.popularity,
                "explicit": t.explicit,
                "bpm": t.bpm,
                "added_at": t.added_at,
                "release_year": t.release_year,
                "genres": t.genres,
                "tags": t.subgenre_tags[:MAX_TAGS_PER_TRACK],
            }
            for t in analysis.tracks
        ],
    }


def load(playlist_id: str) -> dict | None:
    with _lock:
        if playlist_id in _memo:
            return _memo[playlist_id]

    try:
        digest = json.loads(_path(playlist_id).read_text(encoding="utf-8"))
        if digest.get("version") != VERSION:
            digest = None
    except (OSError, json.JSONDecodeError):
        digest = None

    with _lock:
        _memo[playlist_id] = digest
    return digest


def save(analysis: PlaylistAnalysis, *, has_audio: bool) -> None:
    playlist_id = analysis.playlist.id
    current = load(playlist_id)

    # Um resumo sem BPM não substitui um com BPM da mesma versão da playlist.
    if (
        current
        and current.get("has_audio")
        and not has_audio
        and current.get("snapshot_id") == analysis.playlist.snapshot_id
    ):
        return

    digest = digest_from_analysis(analysis, has_audio=has_audio)
    path = _path(playlist_id)
    try:
        STORE_PATH.mkdir(parents=True, exist_ok=True)
        # Escreve ao lado e troca de uma vez: um processo interrompido no meio
        # nunca deixa um JSON pela metade para a próxima leitura.
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(digest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logger.warning("Não consegui gravar o resumo de %s em %s", playlist_id, path)
        return

    with _lock:
        _memo[playlist_id] = digest


def is_fresh(digest: dict | None, snapshot_id: str | None) -> bool:
    """O resumo corresponde à versão atual da playlist?

    Sem snapshot de nenhum dos lados não há como saber, e aí vale o resumo: é
    melhor mostrar algo possivelmente velho do que reanalisar sem fim.
    """
    if digest is None:
        return False
    if not snapshot_id or not digest.get("snapshot_id"):
        return True
    return digest["snapshot_id"] == snapshot_id


def clear_memo() -> None:
    with _lock:
        _memo.clear()
