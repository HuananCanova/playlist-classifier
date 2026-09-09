"""Peças do OAuth do Spotify que não dependem de uma requisição HTTP.

`auth.py` cuida do fluxo do navegador, onde os tokens vivem no cookie de
sessão. O servidor MCP não tem sessão nenhuma: é um processo iniciado pelo
cliente MCP, com um refresh token no `.env`. As duas rotas precisam falar com
o mesmo endpoint de token, então ele mora aqui.
"""
import httpx

from .config import get_settings

SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"


class SpotifyAuthError(RuntimeError):
    """O refresh token não vale mais, ou as credenciais do app estão erradas."""


async def access_token_from_refresh_token(refresh_token: str | None = None) -> str:
    """Troca um refresh token por um access token válido.

    Usado fora do ciclo de requisição — hoje, pelo servidor MCP.
    """
    settings = get_settings()
    token = refresh_token or settings.spotify_refresh_token
    if not token:
        raise SpotifyAuthError("Nenhum refresh token configurado.")

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            SPOTIFY_TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": token},
            auth=(settings.spotify_client_id, settings.spotify_client_secret),
        )

    if resp.status_code != 200:
        raise SpotifyAuthError(
            f"O Spotify recusou o refresh token (HTTP {resp.status_code}). "
            "Gere outro com: python -m scripts.spotify_refresh_token"
        )

    return resp.json()["access_token"]
