"""Evidência por faixa guardada para reclassificar subgênero sem rede.

Diferente de `enrichment_store` (cache com validade por chave de busca), aqui a
chave é o id da faixa e não há TTL: o que importa é poder refazer a
classificação offline quando a taxonomia ou os pesos mudarem. As tags do Last.fm
ficam separadas (artista e faixa) e com peso, porque a fonte pesa diferente no
blend.
"""
import time
from dataclasses import dataclass

from . import db
from .enrichment_store import _decode_tags, _encode_tags
from .taxonomy import Tag


@dataclass
class TrackEvidence:
    track_id: str
    # None = não buscado; [] = buscado e sem tags.
    artist_tags: list[Tag] | None = None
    track_tags: list[Tag] | None = None
    bpm: float | None = None
    deezer_id: int | None = None
    # None = Deezer nunca consultado. Com bpm/deezer_id None: consultado, sem match.
    deezer_checked_at: float | None = None


def _from_row(row) -> TrackEvidence:
    return TrackEvidence(
        track_id=row["track_id"],
        artist_tags=None if row["artist_tags"] is None else _decode_tags(row["artist_tags"]),
        track_tags=None if row["track_tags"] is None else _decode_tags(row["track_tags"]),
        bpm=row["bpm"],
        deezer_id=row["deezer_id"],
        deezer_checked_at=row["deezer_checked_at"],
    )


def get_many(track_ids: list[str]) -> dict[str, TrackEvidence]:
    found: dict[str, TrackEvidence] = {}
    ids = list(dict.fromkeys(track_ids))
    # Blocos abaixo do limite de variáveis do SQLite.
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        marks = ",".join("?" * len(chunk))
        for row in db.query(f"SELECT * FROM track_evidence WHERE track_id IN ({marks})", chunk):
            found[row["track_id"]] = _from_row(row)
    return found


def put(ev: TrackEvidence) -> None:
    """Grava mesclando com o que já existe: campo None nunca apaga valor guardado."""
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM track_evidence WHERE track_id = ?", (ev.track_id,)).fetchone()
        old = _from_row(row) if row is not None else TrackEvidence(ev.track_id)

        def pick(new, stored):
            return stored if new is None else new

        artist_tags = pick(ev.artist_tags, old.artist_tags)
        track_tags = pick(ev.track_tags, old.track_tags)
        conn.execute(
            "INSERT OR REPLACE INTO track_evidence "
            "(track_id, artist_tags, track_tags, bpm, deezer_id, deezer_checked_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ev.track_id,
                None if artist_tags is None else _encode_tags(artist_tags),
                None if track_tags is None else _encode_tags(track_tags),
                pick(ev.bpm, old.bpm),
                pick(ev.deezer_id, old.deezer_id),
                pick(ev.deezer_checked_at, old.deezer_checked_at),
                time.time(),
            ),
        )


def missing(track_ids: list[str]) -> list[str]:
    """Ids sem linha ou com alguma fonte ainda não consultada (na ordem dada)."""
    have = get_many(track_ids)
    out = []
    for tid in dict.fromkeys(track_ids):
        ev = have.get(tid)
        if ev is None or ev.artist_tags is None or ev.track_tags is None or ev.deezer_checked_at is None:
            out.append(tid)
    return out
