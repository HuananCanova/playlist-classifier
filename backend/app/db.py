"""SQLite: o que o app precisa lembrar entre reinícios e entre usuários.

Antes disso o estado vivia em caches de memória (perdidos a cada reinício) e em
JSONs soltos por pasta. Para o app ficar no ar para qualquer pessoa, o trabalho
caro — ler playlists no Spotify, tags no Last.fm, BPM no Deezer — precisa ser
feito uma vez e reaproveitado, e isso pede um lugar com transação, índice e
esquema versionado.

Por que SQLite e não um servidor de banco:

- Um arquivo só, sem serviço ao lado. Num container com volume persistente ele
  aguenta com folga o volume de um app como este.
- O app já precisa rodar em **uma instância**: o controle de ritmo do Spotify
  (spotify_client) vive no processo. Um banco em rede não compraria nada agora.
- A camada é fina e o SQL é padrão: migrar para Postgres depois é trocar a
  conexão, não reescrever os módulos que usam `db`.

Uma conexão compartilhada, protegida por lock. As operações aqui são de
microssegundos, então serializar custa menos do que gerenciar uma conexão por
thread — e deixa os testes trocarem o arquivo com uma chamada. Chame as funções
deste módulo fora do event loop (`asyncio.to_thread`) quando o volume for alto.
"""
import json
import logging
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / ".data"
DB_FILENAME = "app.sqlite3"

# Cada item é uma migração; a posição + 1 é a versão (PRAGMA user_version).
# Só se acrescenta no fim: mudar uma migração já aplicada não roda de novo.
MIGRATIONS: list[str] = [
    # 1 — dados externos por faixa/artista, análises e listagens.
    """
    CREATE TABLE lastfm_artist_tags (
        artist_key TEXT PRIMARY KEY,
        tags       TEXT NOT NULL,
        fetched_at REAL NOT NULL
    );

    CREATE TABLE lastfm_track_tags (
        track_key  TEXT PRIMARY KEY,
        tags       TEXT NOT NULL,
        fetched_at REAL NOT NULL
    );

    -- deezer_id NULL = procurado e não encontrado (também vale a pena lembrar).
    CREATE TABLE deezer_matches (
        track_key  TEXT PRIMARY KEY,
        deezer_id  INTEGER,
        bpm        REAL,
        deezer_url TEXT,
        fetched_at REAL NOT NULL
    );

    -- Metadados de faixa do Spotify: nome, artistas, álbum, capa, duração.
    CREATE TABLE spotify_tracks (
        track_id   TEXT PRIMARY KEY,
        data       TEXT NOT NULL,
        fetched_at REAL NOT NULL
    );

    -- Análise completa, válida enquanto o snapshot_id da playlist não muda.
    CREATE TABLE playlist_analyses (
        playlist_id TEXT PRIMARY KEY,
        snapshot_id TEXT,
        has_audio   INTEGER NOT NULL,
        format      INTEGER NOT NULL,
        analysis    TEXT NOT NULL,
        saved_at    REAL NOT NULL
    );

    -- Resumo enxuto que o perfil agrega (profile_store).
    CREATE TABLE playlist_digests (
        playlist_id TEXT PRIMARY KEY,
        snapshot_id TEXT,
        has_audio   INTEGER NOT NULL,
        format      INTEGER NOT NULL,
        digest      TEXT NOT NULL,
        saved_at    REAL NOT NULL
    );

    -- Última listagem de playlists de cada conta.
    CREATE TABLE playlist_listings (
        user_key  TEXT PRIMARY KEY,
        playlists TEXT NOT NULL,
        saved_at  REAL NOT NULL
    );
    """,
    # 2 — sessões no servidor (sessions.py). O cookie leva só um id aleatório;
    # aqui fica o hash dele e os dados da sessão criptografados.
    """
    CREATE TABLE sessions (
        id_hash    TEXT PRIMARY KEY,
        user_id    TEXT,
        data       BLOB NOT NULL,
        created_at REAL NOT NULL,
        last_seen  REAL NOT NULL,
        expires_at REAL NOT NULL
    );

    CREATE INDEX sessions_expires_at ON sessions (expires_at);
    CREATE INDEX sessions_user_id ON sessions (user_id);
    """,
]

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_path_override: Path | None = None


def data_dir() -> Path:
    configured = get_settings().data_dir
    return Path(configured) if configured else DEFAULT_DATA_DIR


def db_path() -> Path:
    return _path_override or data_dir() / DB_FILENAME


def use_path(path: Path | None) -> None:
    """Troca o arquivo do banco (testes). `None` volta ao padrão."""
    global _path_override
    with _lock:
        close()
        _path_override = path


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn

    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # WAL: leitura não espera escrita. NORMAL: sem fsync a cada commit, o que
    # no WAL ainda é seguro contra corrupção (no pior caso perde o último commit).
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    _migrate(conn)
    _conn = conn
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, script in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        logger.info("Aplicando migração %d do banco", version)
        # executescript faz COMMIT antes; o BEGIN aqui deixa a migração atômica.
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Várias escritas de uma vez, tudo ou nada."""
    with _lock:
        conn = _connect()
        conn.execute("BEGIN")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with _lock:
        return _connect().execute(sql, tuple(params)).fetchall()


def query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    with _lock:
        return _connect().execute(sql, tuple(params)).fetchone()


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    with _lock:
        _connect().execute(sql, tuple(params))


def executemany(sql: str, rows: Iterable[Iterable[Any]]) -> None:
    rows = [tuple(r) for r in rows]
    if not rows:
        return
    with transaction() as conn:
        conn.executemany(sql, rows)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
