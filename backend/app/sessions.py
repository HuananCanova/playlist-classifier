"""Sessões guardadas no servidor, com só um id opaco no cookie.

Antes, o `SessionMiddleware` do Starlette guardava a sessão inteira dentro do
cookie: assinado (não dá para forjar), mas não criptografado. O access token e
o refresh token do Spotify viajavam em toda requisição e ficavam no navegador,
legíveis por qualquer um com acesso ao cookie. Para um app aberto a qualquer
pessoa isso não serve — um refresh token vazado dá acesso à conta por meses.

Aqui o cookie leva só um id aleatório de 256 bits. A sessão mora no banco:

- **Só o hash do id** é guardado. Um vazamento do banco não entrega sessões
  que possam ser usadas.
- **Os dados são criptografados** (Fernet: AES-128-CBC + HMAC-SHA256), com uma
  chave derivada do `SESSION_SECRET` ou dada em `SESSION_ENCRYPTION_KEY`.
- **Expira** após `SESSION_TTL` sem uso, e o id é trocado no login para evitar
  fixação de sessão (`rotate`).

O middleware coloca a sessão em `scope["session"]`, o mesmo lugar do
`SessionMiddleware`, então `request.session` continua funcionando igual no
resto do app.
"""
import asyncio
import base64
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import db
from .config import DEV_SESSION_SECRET, Settings, get_settings

logger = logging.getLogger(__name__)

COOKIE_NAME = "pc_session"
SESSION_TTL = 30 * 24 * 60 * 60
# A validade é estendida no uso, mas no máximo uma vez por este intervalo:
# gravar no banco a cada requisição seria custo sem ganho.
TOUCH_EVERY = 60 * 60

_fernet: Fernet | None = None


def _cipher() -> Fernet:
    global _fernet
    if _fernet is None:
        settings = get_settings()
        if settings.session_encryption_key:
            key = settings.session_encryption_key.encode()
        else:
            raw = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"playlist-classifier/sessions",
                info=b"session-data",
            ).derive(settings.session_secret.encode())
            key = base64.urlsafe_b64encode(raw)
        _fernet = Fernet(key)
    return _fernet


def reset_cipher() -> None:
    """Esquece a chave carregada (testes que trocam a configuração)."""
    global _fernet
    _fernet = None


def check_settings(settings: Settings) -> None:
    """Recusa subir em produção com o segredo de desenvolvimento.

    Com o segredo padrão, que está no repositório, qualquer um derivaria a
    chave das sessões. `SESSION_COOKIE_SECURE=true` é o sinal de produção."""
    if settings.session_cookie_secure and settings.session_secret == DEV_SESSION_SECRET and not settings.session_encryption_key:
        raise RuntimeError(
            "SESSION_SECRET ainda é o valor de desenvolvimento. Gere um com "
            "`openssl rand -hex 32` antes de subir com SESSION_COOKIE_SECURE=true."
        )
    if settings.session_cookie_samesite.lower() == "none" and not settings.session_cookie_secure:
        raise RuntimeError("SESSION_COOKIE_SAMESITE=none exige SESSION_COOKIE_SECURE=true.")


def _hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


def new_id() -> str:
    return secrets.token_urlsafe(32)


@dataclass
class StoredSession:
    data: dict
    last_seen: float


def load(session_id: str) -> StoredSession | None:
    row = db.query_one("SELECT data, last_seen, expires_at FROM sessions WHERE id_hash = ?", (_hash(session_id),))
    if row is None:
        return None
    if row["expires_at"] <= time.time():
        delete(session_id)
        return None
    try:
        data = json.loads(_cipher().decrypt(row["data"]))
    except (InvalidToken, ValueError):
        # Chave trocada ou dado corrompido: a sessão não vale mais.
        delete(session_id)
        return None
    return StoredSession(data=data, last_seen=row["last_seen"])


def save(session_id: str, data: dict) -> None:
    now = time.time()
    user_id = (data.get("me") or {}).get("id")
    blob = _cipher().encrypt(json.dumps(data, ensure_ascii=False).encode())
    db.execute(
        "INSERT INTO sessions (id_hash, user_id, data, created_at, last_seen, expires_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id_hash) DO UPDATE SET user_id = excluded.user_id, data = excluded.data, "
        "last_seen = excluded.last_seen, expires_at = excluded.expires_at",
        (_hash(session_id), user_id, blob, now, now, now + SESSION_TTL),
    )


def touch(session_id: str) -> None:
    now = time.time()
    db.execute(
        "UPDATE sessions SET last_seen = ?, expires_at = ? WHERE id_hash = ?",
        (now, now + SESSION_TTL, _hash(session_id)),
    )


def delete(session_id: str) -> None:
    db.execute("DELETE FROM sessions WHERE id_hash = ?", (_hash(session_id),))


def delete_expired() -> int:
    with db.transaction() as conn:
        return conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),)).rowcount


def rotate(request) -> None:
    """Pede um id novo para esta sessão ao fim da requisição (use no login).

    Sem isso, um id plantado no navegador de alguém antes do login continuaria
    valendo depois dele — e daria a quem plantou a sessão autenticada."""
    request.scope["session_rotate"] = True


class ServerSessionMiddleware:
    def __init__(self, app: ASGIApp, *, secure: bool, same_site: str) -> None:
        self.app = app
        self.secure = secure
        self.same_site = same_site.lower()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        cookie_id = HTTPConnection(scope).cookies.get(COOKIE_NAME)
        stored = await asyncio.to_thread(load, cookie_id) if cookie_id else None
        initial = stored.data if stored else {}
        # Cópia profunda: comparar com `initial` no fim é o que diz se mudou.
        scope["session"] = json.loads(json.dumps(initial))

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                await self._commit(scope, message, cookie_id if stored else None, stored, initial, cookie_id)
            await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _commit(
        self,
        scope: Scope,
        message: Message,
        session_id: str | None,
        stored: StoredSession | None,
        initial: dict,
        cookie_id: str | None,
    ) -> None:
        session = scope["session"]
        headers = MutableHeaders(scope=message)

        if not session:
            if session_id:
                await asyncio.to_thread(delete, session_id)
            if cookie_id:
                headers.append("Set-Cookie", self._cookie("", 0))
            return

        stale = stored is not None and time.time() - stored.last_seen > TOUCH_EVERY
        if session_id is None or scope.get("session_rotate"):
            if session_id:
                await asyncio.to_thread(delete, session_id)
            fresh_id = new_id()
            await asyncio.to_thread(save, fresh_id, session)
            headers.append("Set-Cookie", self._cookie(fresh_id, SESSION_TTL))
        elif session != initial:
            await asyncio.to_thread(save, session_id, session)
            if stale:
                headers.append("Set-Cookie", self._cookie(session_id, SESSION_TTL))
        elif stale:
            await asyncio.to_thread(touch, session_id)
            headers.append("Set-Cookie", self._cookie(session_id, SESSION_TTL))

    def _cookie(self, value: str, max_age: int) -> str:
        parts = [f"{COOKIE_NAME}={value}", "Path=/", f"Max-Age={max_age}", "HttpOnly", f"SameSite={self.same_site}"]
        if self.secure:
            parts.append("Secure")
        return "; ".join(parts)
