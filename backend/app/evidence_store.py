"""Evidência por faixa guardada para reclassificar subgênero sem rede.

Diferente de `enrichment_store` (cache com validade por chave de busca), aqui a
chave é o id da faixa e não há TTL: o que importa é poder refazer a
classificação offline quando a taxonomia ou os pesos mudarem. As tags do Last.fm
ficam separadas (artista e faixa) e com peso, porque a fonte pesa diferente no
blend.
"""
import time
from dataclasses import dataclass

from . import db, deezer_client
from .enrichment_store import decode_tags, encode_tags
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
    # Selo do lançamento (Deezer). None = não consultado; "" = o álbum não tem
    # selo. Só pode ser perguntado depois que existe `deezer_id`. Com
    # `label_checked_at` e label None: consultado, mas o match não conferiu.
    label: str | None = None
    label_checked_at: float | None = None
    # O deezer_id de onde o selo veio: diferente do atual, o selo é de outro
    # lançamento e precisa ser perguntado de novo.
    label_deezer_id: int | None = None


def _from_row(row) -> TrackEvidence:
    return TrackEvidence(
        track_id=row["track_id"],
        artist_tags=None if row["artist_tags"] is None else decode_tags(row["artist_tags"]),
        track_tags=None if row["track_tags"] is None else decode_tags(row["track_tags"]),
        bpm=row["bpm"],
        deezer_id=row["deezer_id"],
        deezer_checked_at=row["deezer_checked_at"],
        label=row["label"],
        label_checked_at=row["label_checked_at"],
        label_deezer_id=row["label_deezer_id"],
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
        # Uma consulta de selo grava selo e origem juntos, como estão: "não
        # conferiu" (label None) substitui o selo de um match anterior.
        if ev.label_checked_at is not None:
            label, label_deezer_id = ev.label, ev.label_deezer_id
        else:
            label, label_deezer_id = pick(ev.label, old.label), pick(ev.label_deezer_id, old.label_deezer_id)
        conn.execute(
            "INSERT OR REPLACE INTO track_evidence "
            "(track_id, artist_tags, track_tags, bpm, deezer_id, deezer_checked_at, label, label_checked_at, "
            "label_deezer_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ev.track_id,
                None if artist_tags is None else encode_tags(artist_tags),
                None if track_tags is None else encode_tags(track_tags),
                pick(ev.bpm, old.bpm),
                pick(ev.deezer_id, old.deezer_id),
                pick(ev.deezer_checked_at, old.deezer_checked_at),
                label,
                pick(ev.label_checked_at, old.label_checked_at),
                label_deezer_id,
                time.time(),
            ),
        )


def deezer_fields(info: dict) -> dict | None:
    """O que gravar de uma resposta de `deezer_client.get_track_info`, ou None se foi falha.

    Achou (com id) → bpm, id e quando; `NotFound` (o Deezer respondeu que não
    tem) → só quando; falha ou detalhe incompleto → nada."""
    if isinstance(info, deezer_client.NotFound):
        return {"deezer_checked_at": time.time()}
    if isinstance(info, deezer_client.Incomplete) or info.get("deezer_id") is None:
        return None
    return {"deezer_id": info["deezer_id"], "bpm": info.get("bpm"), "deezer_checked_at": time.time()}


def missing(track_ids: list[str]) -> list[str]:
    """Ids sem linha ou com alguma fonte ainda não consultada (na ordem dada).

    O selo só conta quando há `deezer_id`: sem correspondência no Deezer não há
    álbum a perguntar, e a faixa não pode ficar eternamente "faltando". Selo de
    outra correspondência (ou de origem desconhecida, guardado antes de ela ser
    registrada) também falta: pode ser de outro lançamento."""
    have = get_many(track_ids)
    out = []
    for tid in dict.fromkeys(track_ids):
        ev = have.get(tid)
        if (
            ev is None
            or ev.artist_tags is None
            or ev.track_tags is None
            or ev.deezer_checked_at is None
            or (ev.deezer_id is not None and (ev.label_checked_at is None or ev.label_deezer_id != ev.deezer_id))
        ):
            out.append(tid)
    return out
