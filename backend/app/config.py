"""Application configuration, loaded from environment variables / .env file."""
from functools import lru_cache
from pathlib import Path

# O valor que vem no .env.example. Serve para desenvolvimento e é recusado
# em produção — por isso precisa ser uma constante, e não texto solto.
DEV_SECRET = "change_me_to_a_random_secret"

from pydantic_settings import BaseSettings, SettingsConfigDict

# Caminho absoluto: assim o backend sobe de qualquer diretório de trabalho
# (backend/, raiz do repo, runner da IDE) e não só de dentro de backend/.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str = "http://127.0.0.1:8000/api/auth/callback"

    lastfm_api_key: str

    # Só o servidor MCP usa: ele roda fora do navegador, sem cookie de sessão.
    # Obtenha uma vez com `python -m scripts.spotify_refresh_token`.
    spotify_refresh_token: str = ""

    # Varre as playlists ainda não indexadas quando o app abre. Desligado por
    # padrão: varreduras automáticas a cada visita somaram volume suficiente
    # para o Spotify suspender o app por 18 horas. Com `false`, a varredura só
    # roda pelo botão da busca ou do perfil.
    auto_index: bool = False

    # Provedor do chat: "anthropic" (alvo real) ou "groq" (testes sem custo).
    # Sem chave nenhuma, o app funciona normalmente e o chat some da interface.
    chat_provider: str = "anthropic"
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    # Precisa suportar tool calling — o agente funciona chamando ferramentas.
    groq_model: str = "openai/gpt-oss-120b"

    frontend_url: str = "http://127.0.0.1:5173"
    session_secret: str = DEV_SECRET

    # `production` liga o cookie só-HTTPS e passa a exigir um SESSION_SECRET
    # de verdade. Fora isso o app não muda: continua sendo o mesmo processo.
    environment: str = "development"

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    # Scopes needed to read the user's playlists (including private/collaborative ones)
    spotify_scopes: str = "playlist-read-private playlist-read-collaborative user-library-read"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()

    # Falha no boot, não na primeira requisição: com o segredo padrão
    # qualquer pessoa que leia este repositório consegue assinar um cookie
    # de sessão válido — e a sessão é o que guarda os tokens do Spotify.
    if settings.is_production and settings.session_secret == DEV_SECRET:
        raise RuntimeError(
            "SESSION_SECRET ainda é o valor de exemplo. Gere um com "
            "`openssl rand -hex 32` antes de subir com ENVIRONMENT=production."
        )
    return settings
