"""Resumos compactos de cada playlist, guardados no banco para o perfil.

O perfil agrega a conta inteira, e analisar dezenas de playlists do zero a cada
visita seria lento e caro no rate limit do Spotify. Então cada análise feita em
qualquer lugar do app (página da playlist, varredura da busca, varredura do
perfil) deixa aqui um resumo com só o que o perfil usa.

Um resumo vale enquanto o `snapshot_id` da playlist não muda — o Spotify troca
esse id a cada alteração de conteúdo, então ele responde exatamente "preciso
analisar de novo?".

A chave é só o id da playlist, sem o usuário: o resumo descreve o conteúdo da
playlist, e o perfil só lê resumos das playlists que o próprio Spotify listou
para quem está logado. A permissão continua vindo do Spotify.

Os resumos moravam em JSONs soltos em `backend/.profile_cache`. Na primeira
leitura do processo, os que ainda estiverem lá são importados para o banco (sem
sobrescrever nada mais novo), então quem atualiza não refaz a varredura.
"""
import json
import logging
import threading
import time
from pathlib import Path

from . import db
from .models import PlaylistAnalysis

logger = logging.getLogger(__name__)

# Pasta antiga dos resumos em JSON; só lida para importar.
STORE_PATH = Path(__file__).resolve().parent.parent / ".profile_cache"

# Sobe quando o formato muda; resumos de outra versão são tratados como ausentes.
VERSION = 1

# Tags por faixa no resumo. As distribuições do perfil só olham o topo, e isso
# mantém o resumo de uma playlist de 500 faixas na casa das centenas de KB.
MAX_TAGS_PER_TRACK = 8

# O perfil lê todos os resumos da conta a cada visita; decodificar JSON de
# centenas de KB toda vez seria o gargalo, então o que já foi lido fica aqui.
_memo: dict[str, dict | None] = {}
_lock = threading.Lock()
_imported = False


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


def _import_legacy() -> None:
    """Traz para o banco os resumos em JSON da versão anterior, uma vez por processo."""
    global _imported
    with _lock:
        if _imported:
            return
        _imported = True

    if not STORE_PATH.is_dir():
        return
    rows = []
    for path in STORE_PATH.glob("*.json"):
        try:
            digest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if digest.get("version") != VERSION or not (digest.get("playlist") or {}).get("id"):
            continue
        rows.append(
            (
                digest["playlist"]["id"],
                digest.get("snapshot_id"),
                int(bool(digest.get("has_audio"))),
                VERSION,
                db.dumps(digest),
                digest.get("saved_at") or time.time(),
            )
        )
    if rows:
        # OR IGNORE: um resumo já no banco é pelo menos tão novo quanto o JSON.
        db.executemany(
            "INSERT OR IGNORE INTO playlist_digests (playlist_id, snapshot_id, has_audio, format, digest, saved_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        logger.info("Importados %d resumos de %s para o banco", len(rows), STORE_PATH)


def load(playlist_id: str) -> dict | None:
    _import_legacy()
    with _lock:
        if playlist_id in _memo:
            return _memo[playlist_id]

    row = db.query_one("SELECT format, digest FROM playlist_digests WHERE playlist_id = ?", (playlist_id,))
    digest = json.loads(row["digest"]) if row is not None and row["format"] == VERSION else None

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
    db.execute(
        "INSERT OR REPLACE INTO playlist_digests (playlist_id, snapshot_id, has_audio, format, digest, saved_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (playlist_id, digest["snapshot_id"], int(has_audio), VERSION, db.dumps(digest), digest["saved_at"]),
    )

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
    """Esquece o que já foi lido (e permite importar de novo) — para testes."""
    global _imported
    with _lock:
        _memo.clear()
        _imported = False
