"""Spotify OAuth (Authorization Code + PKCE) and session handling.

Tokens are kept server-side in a signed, httpOnly session cookie (via Starlette's
SessionMiddleware) — never exposed to the frontend JS. This is fine for a
single-user, local-dev app; for a multi-user deployment you'd swap this for a
real session store (Redis, DB) keyed by an opaque session id.
"""
import base64
import hashlib
import secrets
import time
import urllib.parse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"


def _make_pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


@router.get("/login")
async def login(request: Request):
    settings = get_settings()
    state = secrets.token_urlsafe(16)
    code_verifier, code_challenge = _make_pkce_pair()

    # Stashed in the session only long enough to validate the callback.
    request.session["oauth_state"] = state
    request.session["oauth_code_verifier"] = code_verifier

    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "state": state,
        "scope": settings.spotify_scopes,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
    }
    return RedirectResponse(f"{SPOTIFY_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}")


@router.get("/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    settings = get_settings()

    if error:
        return RedirectResponse(f"{settings.frontend_url}/login?error={urllib.parse.quote(error)}")

    expected_state = request.session.pop("oauth_state", None)
    code_verifier = request.session.pop("oauth_code_verifier", None)
    if not code or not state or state != expected_state or not code_verifier:
        return RedirectResponse(f"{settings.frontend_url}/login?error=invalid_state")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            SPOTIFY_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.spotify_redirect_uri,
                "client_id": settings.spotify_client_id,
                "code_verifier": code_verifier,
            },
            # PKCE public-client flow still lets us also send the client secret since
            # this is a confidential (server-side) app — belt and suspenders.
            auth=(settings.spotify_client_id, settings.spotify_client_secret),
        )

    if resp.status_code != 200:
        return RedirectResponse(f"{settings.frontend_url}/login?error=token_exchange_failed")

    token_data = resp.json()
    _store_tokens(request, token_data)

    return RedirectResponse(f"{settings.frontend_url}/playlists")


def _store_tokens(request: Request, token_data: dict) -> None:
    request.session["access_token"] = token_data["access_token"]
    request.session["refresh_token"] = token_data.get("refresh_token", request.session.get("refresh_token"))
    request.session["expires_at"] = time.time() + token_data.get("expires_in", 3600) - 30  # 30s safety margin


@router.get("/me")
async def me(request: Request):
    if "access_token" not in request.session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = await get_valid_access_token(request)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.spotify.com/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Not authenticated")
    profile = resp.json()
    return {
        "id": profile.get("id"),
        "display_name": profile.get("display_name"),
        "image": (profile.get("images") or [{}])[0].get("url"),
    }


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


async def get_valid_access_token(request: Request) -> str:
    """Returns a valid access token, refreshing it first if it's expired."""
    if "access_token" not in request.session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if time.time() < request.session.get("expires_at", 0):
        return request.session["access_token"]

    refresh_token = request.session.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Session expired, please log in again")

    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            SPOTIFY_TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(settings.spotify_client_id, settings.spotify_client_secret),
        )
    if resp.status_code != 200:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session expired, please log in again")

    _store_tokens(request, resp.json())
    return request.session["access_token"]
