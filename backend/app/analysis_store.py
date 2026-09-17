"""Análises completas de playlist e listagens de conta, guardadas no banco.

Abrir uma playlist custava de novo Spotify + Last.fm + Deezer toda vez que o
cache de 10 minutos em memória expirava. Aqui a análise pronta fica guardada e
vale enquanto o `snapshot_id` da playlist não muda — o Spotify troca esse id a
cada alteração de conteúdo, então ele responde exatamente "preciso refazer?".

**Permissão.** A chave de uma análise é só o id da playlist: ela descreve o
conteúdo, não a pessoa. Quem decide se uma conta pode ver uma análise guardada
é a listagem daquela conta, que vem do próprio Spotify (`playlists.py`). Este
módulo não faz essa checagem — quem lê daqui precisa ter feito.

A prévia de áudio do Deezer é uma URL assinada que expira em minutos, então não
é guardada: a faixa guarda o `deezer_id`, e a prévia é resolvida na hora do play.
"""
import json
import time
from dataclasses import dataclass

from pydantic import ValidationError

from . import db
from .models import PlaylistAnalysis, PlaylistSummary

# Sobe quando o formato de PlaylistAnalysis muda de um jeito incompatível;
# análises de outro formato são tratadas como ausentes e refeitas.
ANALYSIS_FORMAT = 1


@dataclass
class StoredAnalysis:
    analysis: PlaylistAnalysis
    has_audio: bool
    saved_at: float


def snapshot_matches(stored: str | None, current: str | None) -> bool:
    """Sem snapshot de um dos lados não há como saber; aí vale o que existe.

    Melhor mostrar algo possivelmente velho do que reanalisar sem fim."""
    if not stored or not current:
        return True
    return stored == current


def load(playlist_id: str, snapshot_id: str | None) -> StoredAnalysis | None:
    """A análise guardada, se corresponde a esta versão da playlist."""
    row = db.query_one(
        "SELECT snapshot_id, has_audio, format, analysis, saved_at FROM playlist_analyses WHERE playlist_id = ?",
        (playlist_id,),
    )
    if row is None or row["format"] != ANALYSIS_FORMAT:
        return None
    if not snapshot_matches(row["snapshot_id"], snapshot_id):
        return None
    try:
        analysis = PlaylistAnalysis.model_validate_json(row["analysis"])
    except ValidationError:
        return None
    return StoredAnalysis(analysis=analysis, has_audio=bool(row["has_audio"]), saved_at=row["saved_at"])


def save(analysis: PlaylistAnalysis, *, has_audio: bool) -> None:
    """Guarda a análise sem as URLs de prévia (expiram antes de serem usadas).

    Uma análise sem áudio não substitui uma com áudio da mesma versão da
    playlist: seria jogar fora o BPM que já foi buscado."""
    playlist = analysis.playlist
    row = db.query_one(
        "SELECT snapshot_id, has_audio, format FROM playlist_analyses WHERE playlist_id = ?", (playlist.id,)
    )
    if (
        row is not None
        and not has_audio
        and row["has_audio"]
        and row["format"] == ANALYSIS_FORMAT
        and row["snapshot_id"] == playlist.snapshot_id
    ):
        return

    stripped = analysis.model_copy(
        update={"tracks": [t.model_copy(update={"preview_url": None}) for t in analysis.tracks]}
    )
    db.execute(
        "INSERT OR REPLACE INTO playlist_analyses (playlist_id, snapshot_id, has_audio, format, analysis, saved_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (playlist.id, playlist.snapshot_id, int(has_audio), ANALYSIS_FORMAT, stripped.model_dump_json(), time.time()),
    )


# ── listagens ───────────────────────────────────────────────────────────────


def load_listing(user_key: str) -> tuple[list[PlaylistSummary], float] | None:
    row = db.query_one("SELECT playlists, saved_at FROM playlist_listings WHERE user_key = ?", (user_key,))
    if row is None:
        return None
    try:
        return [PlaylistSummary(**p) for p in json.loads(row["playlists"])], row["saved_at"]
    except (ValueError, TypeError, ValidationError):
        return None


def save_listing(user_key: str, playlists: list[PlaylistSummary], saved_at: float | None = None) -> None:
    db.execute(
        "INSERT OR REPLACE INTO playlist_listings (user_key, playlists, saved_at) VALUES (?, ?, ?)",
        (user_key, db.dumps([p.model_dump() for p in playlists]), saved_at or time.time()),
    )
