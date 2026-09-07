"""Application configuration, loaded from environment variables / .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str = "http://127.0.0.1:8000/api/auth/callback"

    lastfm_api_key: str

    # Opcional: sem ela o app funciona normalmente, só sem o chat com IA.
    anthropic_api_key: str = ""

    frontend_url: str = "http://127.0.0.1:5173"
    session_secret: str = "dev-only-insecure-secret-change-me"

    # Scopes needed to read the user's playlists (including private/collaborative ones)
    spotify_scopes: str = "playlist-read-private playlist-read-collaborative user-library-read"


@lru_cache
def get_settings() -> Settings:
    return Settings()
