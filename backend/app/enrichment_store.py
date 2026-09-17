"""Dados externos por faixa e por artista, guardados no banco com validade.

Tags do Last.fm, correspondência no Deezer e metadados de faixa do Spotify
quase nunca mudam, e são o grosso do tempo de uma análise: uma playlist de 300
faixas custa ~300 chamadas ao Last.fm e até ~600 ao Deezer. Guardando por faixa
(e não só por playlist), duas playlists que dividem artistas pagam uma vez só,
e uma playlist que mudou só busca as faixas novas.

Cada chave é o que o respectivo cliente já usava no cache em memória, então os
dois níveis se completam: memória para a mesma requisição, banco para o resto.

Só se grava resposta de verdade. Falha de rede não entra aqui — senão um
soluço do Last.fm viraria "faixa sem tag" por um mês.
"""
import json
import time

from . import db

DAY = 24 * 60 * 60

# Tags de comunidade mudam devagar; um mês ainda é conservador.
TAGS_TTL = 30 * DAY
# Deezer: correspondência encontrada é estável. "Não encontrada" expira antes,
# porque o catálogo cresce e a busca às vezes falha por grafia.
DEEZER_MATCH_TTL = 30 * DAY
DEEZER_MISS_TTL = 7 * DAY
# Metadados de faixa (nome, álbum, capa): só mudam em reedição de catálogo.
SPOTIFY_TRACK_TTL = 30 * DAY


def _fresh(fetched_at: float, ttl: float) -> bool:
    return time.time() - fetched_at < ttl


# ── Last.fm ─────────────────────────────────────────────────────────────────


def get_artist_tags(artist_key: str) -> list[str] | None:
    row = db.query_one("SELECT tags, fetched_at FROM lastfm_artist_tags WHERE artist_key = ?", (artist_key,))
    if row is None or not _fresh(row["fetched_at"], TAGS_TTL):
        return None
    return json.loads(row["tags"])


def put_artist_tags(artist_key: str, tags: list[str]) -> None:
    db.execute(
        "INSERT OR REPLACE INTO lastfm_artist_tags (artist_key, tags, fetched_at) VALUES (?, ?, ?)",
        (artist_key, db.dumps(tags), time.time()),
    )


def get_track_tags(track_key: str) -> list[str] | None:
    row = db.query_one("SELECT tags, fetched_at FROM lastfm_track_tags WHERE track_key = ?", (track_key,))
    if row is None or not _fresh(row["fetched_at"], TAGS_TTL):
        return None
    return json.loads(row["tags"])


def put_track_tags(track_key: str, tags: list[str]) -> None:
    db.execute(
        "INSERT OR REPLACE INTO lastfm_track_tags (track_key, tags, fetched_at) VALUES (?, ?, ?)",
        (track_key, db.dumps(tags), time.time()),
    )


# ── Deezer ──────────────────────────────────────────────────────────────────


def get_deezer_match(track_key: str) -> dict | None:
    """{'deezer_id', 'bpm', 'deezer_url'} — com `deezer_id` None se não achou.

    None (o retorno) quer dizer "não sei, procure"."""
    row = db.query_one(
        "SELECT deezer_id, bpm, deezer_url, fetched_at FROM deezer_matches WHERE track_key = ?", (track_key,)
    )
    if row is None:
        return None
    ttl = DEEZER_MATCH_TTL if row["deezer_id"] is not None else DEEZER_MISS_TTL
    if not _fresh(row["fetched_at"], ttl):
        return None
    return {"deezer_id": row["deezer_id"], "bpm": row["bpm"], "deezer_url": row["deezer_url"]}


def put_deezer_match(track_key: str, deezer_id: int | None, bpm: float | None, deezer_url: str | None) -> None:
    db.execute(
        "INSERT OR REPLACE INTO deezer_matches (track_key, deezer_id, bpm, deezer_url, fetched_at) VALUES (?, ?, ?, ?, ?)",
        (track_key, deezer_id, bpm, deezer_url, time.time()),
    )


# ── Spotify ─────────────────────────────────────────────────────────────────


def get_spotify_track(track_id: str) -> dict | None:
    row = db.query_one("SELECT data, fetched_at FROM spotify_tracks WHERE track_id = ?", (track_id,))
    if row is None or not _fresh(row["fetched_at"], SPOTIFY_TRACK_TTL):
        return None
    return json.loads(row["data"])


def put_spotify_tracks(tracks: list[dict]) -> None:
    """Grava metadados no formato do objeto de faixa do Spotify (só os campos usados)."""
    now = time.time()
    db.executemany(
        "INSERT OR REPLACE INTO spotify_tracks (track_id, data, fetched_at) VALUES (?, ?, ?)",
        ((t["id"], db.dumps(t), now) for t in tracks if t.get("id")),
    )
