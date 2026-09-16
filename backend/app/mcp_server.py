"""Servidor MCP: expõe as playlists do usuário a qualquer cliente MCP.

O chat de dentro do app roda com escopo fixo — uma playlist ou uma faixa por
conversa — porque lá o agente responde dentro de uma tela e não deve poder
varrer a conta inteira. Aqui o cliente é o próprio dono da conta, então o
escopo se abre: `listar_playlists` existe, e as outras duas ferramentas
recebem o id como parâmetro em vez de tê-lo preso na closure.

O conteúdo das respostas, porém, é exatamente o mesmo — `analisar_playlist_json`
e `analisar_faixa_json` são as funções que o chat também usa. Este arquivo é
só a tradução do registro de ferramentas para o protocolo MCP, do mesmo jeito
que `ai_chat.py` traduz para a API da Anthropic e `ai_chat_groq.py` para a da
OpenAI.

Autenticação: um refresh token do Spotify no `.env`, obtido uma vez com
`python -m scripts.spotify_refresh_token`. Não há sessão HTTP aqui — o
processo é iniciado pelo cliente MCP, não pelo navegador.

Rodar:
    python -m app.mcp_server
"""
import json
import logging

import httpx
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .ai_tools import analisar_faixa_json, analisar_playlist_json
from .config import get_settings
from .spotify_auth import access_token_from_refresh_token
from .spotify_client import SpotifyClient

logger = logging.getLogger(__name__)

server: Server = Server("playlist-classifier")


async def _listar_playlists_json(access_token: str) -> str:
    spotify = SpotifyClient(access_token)
    async with httpx.AsyncClient(timeout=20.0) as client:
        playlists = await spotify.get_all_playlists(client)

    return json.dumps(
        {
            "total": len(playlists),
            "playlists": [
                {
                    "playlist_id": p["id"],
                    "nome": p.get("name") or "Sem nome",
                    "faixas": ((p.get("items") or p.get("tracks") or {}).get("total")),
                    "dono": (p.get("owner") or {}).get("display_name"),
                }
                for p in playlists
                if p is not None
            ],
        },
        ensure_ascii=False,
    )


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="listar_playlists",
            description=(
                "Lista todas as playlists da conta do Spotify, com id, nome e "
                "número de faixas. Use para descobrir o playlist_id antes de "
                "chamar analisar_playlist."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="analisar_playlist",
            description=(
                "Analisa uma playlist: distribuição de gêneros e subgêneros "
                "(tags do Last.fm), artistas mais frequentes e uma amostra das "
                "faixas com suas tags."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "playlist_id": {
                        "type": "string",
                        "description": "Id da playlist no Spotify, como vem de listar_playlists.",
                    }
                },
                "required": ["playlist_id"],
            },
        ),
        types.Tool(
            name="analisar_faixa",
            description=(
                "Detalha uma faixa: tags do Last.fm, tags do artista, BPM e "
                "prévia de áudio pelo Deezer, além dos metadados do Spotify."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "track_id": {
                        "type": "string",
                        "description": "Id da faixa no Spotify.",
                    }
                },
                "required": ["track_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # Um access token por chamada: eles valem uma hora e o processo MCP fica de
    # pé por dias. Renovar sob demanda é mais simples do que vigiar validade.
    token = await access_token_from_refresh_token()

    if name == "listar_playlists":
        payload = await _listar_playlists_json(token)
    elif name == "analisar_playlist":
        payload = await analisar_playlist_json(
            token, await _owner(token), arguments["playlist_id"]
        )
    elif name == "analisar_faixa":
        payload = await analisar_faixa_json(token, arguments["track_id"])
    else:
        payload = json.dumps({"erro": f"Ferramenta desconhecida: {name}"}, ensure_ascii=False)

    return [types.TextContent(type="text", text=payload)]


async def main() -> None:
    settings = get_settings()
    if not settings.spotify_refresh_token:
        raise SystemExit(
            "SPOTIFY_REFRESH_TOKEN não está no backend/.env. Rode uma vez:\n"
            "    cd backend && python -m scripts.spotify_refresh_token"
        )

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())


# ── Dono das chamadas do MCP ────────────────────────────────────────────
#
# O servidor MCP não tem sessão: ele roda com o refresh token do .env, sempre
# da mesma conta. Mas o cache da análise e o índice da busca são separados por
# conta, então ele precisa dizer de quem é — e tem que ser o mesmo id que a
# sessão do navegador usa, senão o MCP teria um acervo paralelo e reanalisaria
# tudo de novo (chamadas ao Spotify à toa).
#
# Uma consulta por processo: o id de uma conta não muda.
_owner_id: str | None = None


async def _owner(token: str) -> str:
    global _owner_id
    if _owner_id is None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            _owner_id = await SpotifyClient(token).get_current_user_id(client) or "mcp"
    return _owner_id
