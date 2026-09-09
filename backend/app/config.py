"""Application configuration, loaded from environment variables / .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str = "http://127.0.0.1:8000/api/auth/callback"

    lastfm_api_key: str

    # Só o servidor MCP usa: ele roda fora do navegador, sem cookie de sessão.
    # Obtenha uma vez com `python -m scripts.spotify_refresh_token`.
    spotify_refresh_token: str = ""

    # Varre as playlists ainda não indexadas quando o app abre. Desligue para
    # que o índice só cresça quando você mandar, pela tela de busca.
    auto_index: bool = True

    # Provedor do chat: "anthropic" (alvo real) ou "groq" (testes sem custo).
    # Sem chave nenhuma, o app funciona normalmente e o chat some da interface.
    chat_provider: str = "anthropic"
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    # Precisa suportar tool calling — o agente funciona chamando ferramentas.
    groq_model: str = "openai/gpt-oss-120b"

    frontend_url: str = "http://127.0.0.1:5173"
    session_secret: str = "dev-only-insecure-secret-change-me"

    # Scopes needed to read the user's playlists (including private/collaborative ones)
    spotify_scopes: str = "playlist-read-private playlist-read-collaborative user-library-read"


@lru_cache
def get_settings() -> Settings:
    return Settings()
