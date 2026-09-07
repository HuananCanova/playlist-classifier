"""As ferramentas do agente — independentes de provedor.

Aqui mora a lógica: o que o agente consegue buscar e com que teto de tamanho.
Os adaptadores (`ai_chat.py` para Claude, `ai_chat_groq.py` para Groq) apenas
traduzem estas funções para o formato de cada API.

Para adicionar busca ou recomendação, escreva a função e registre em
`build_tools()` — os dois provedores ganham a capacidade de uma vez.
"""
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from .genre_analysis import build_playlist_analysis
from .spotify_client import SpotifyClient

# Quantos itens cada ferramenta devolve no máximo. Uma playlist de 500 faixas
# viraria dezenas de milhares de tokens por chamada sem esses tetos.
MAX_PLAYLISTS = 60
MAX_TRACK_SAMPLE = 40
MAX_GENRES = 15


@dataclass(frozen=True)
class Tool:
    """Uma ferramenta, no formato neutro que os dois adaptadores consomem."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema dos argumentos
    run: Callable[..., Awaitable[str]]


def build_tools(access_token: str) -> list[Tool]:
    """Cria as ferramentas ligadas à sessão do usuário.

    O token do Spotify fica capturado no closure, não como parâmetro de
    ferramenta: o modelo nem vê a credencial nem consegue passá-la errada.
    """

    async def listar_playlists() -> str:
        spotify = SpotifyClient(access_token)
        async with httpx.AsyncClient(timeout=20.0) as client:
            raw = await spotify.get_all_playlists(client)

        items = []
        for p in raw[:MAX_PLAYLISTS]:
            if not p:
                continue
            total = (p.get("items") or p.get("tracks") or {}).get("total", 0)
            items.append({"id": p.get("id"), "nome": p.get("name"), "faixas": total})

        return json.dumps(
            {"total_de_playlists": len(raw), "playlists": items}, ensure_ascii=False
        )

    async def analisar_playlist(playlist_id: str) -> str:
        try:
            analysis = await build_playlist_analysis(access_token, playlist_id)
        except httpx.HTTPStatusError as exc:
            # Devolvido como resultado, não levantado: assim o modelo explica o
            # problema ao usuário em vez de a conversa inteira morrer.
            return json.dumps(
                {
                    "erro": "Não consegui ler essa playlist no Spotify "
                    f"(HTTP {exc.response.status_code})."
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "playlist": analysis.playlist.name,
                "total_de_faixas": analysis.playlist.track_count,
                "faixas_sem_genero": analysis.tracks_missing_genre,
                "generos": [
                    {"genero": g.label, "faixas": g.count}
                    for g in analysis.genre_distribution[:MAX_GENRES]
                ],
                "subgeneros": [
                    {"tag": g.label, "faixas": g.count}
                    for g in analysis.subgenre_distribution[:MAX_GENRES]
                ],
                "artistas_frequentes": [
                    {"artista": a.label, "faixas": a.count}
                    for a in analysis.top_artists[:10]
                ],
                "amostra_de_faixas": [
                    {"faixa": t.name, "artistas": t.artists, "tags": t.subgenre_tags[:4]}
                    for t in analysis.tracks[:MAX_TRACK_SAMPLE]
                ],
                "observacao": (
                    f"A amostra mostra {min(MAX_TRACK_SAMPLE, len(analysis.tracks))} "
                    f"de {len(analysis.tracks)} faixas."
                ),
            },
            ensure_ascii=False,
        )

    return [
        Tool(
            name="listar_playlists",
            description=(
                "Lista as playlists do usuário no Spotify, com id, nome e número de "
                "faixas. Use primeiro, para descobrir qual playlist o usuário quer e "
                "pegar o id para as outras ferramentas."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            run=listar_playlists,
        ),
        Tool(
            name="analisar_playlist",
            description=(
                "Analisa os gêneros de uma playlist: distribuição de gêneros e "
                "subgêneros, artistas mais frequentes e uma amostra das faixas com "
                "suas tags. Operação custosa (consulta Spotify e Last.fm faixa a "
                "faixa) — use só nas playlists relevantes para a pergunta."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "playlist_id": {
                        "type": "string",
                        "description": "O id da playlist, obtido em listar_playlists.",
                    }
                },
                "required": ["playlist_id"],
            },
            run=analisar_playlist,
        ),
        # Ponto de extensão: buscar_faixas(...), recomendar(...) entram aqui.
    ]


SYSTEM_PROMPT = """Você é o assistente do Playlist Classifier, um app que analisa \
o gosto musical do usuário a partir das playlists dele no Spotify.

Responda sempre em português do Brasil, de forma direta e conversacional.

Como trabalhar:
- Use as ferramentas para buscar dados reais antes de responder qualquer coisa \
sobre as playlists do usuário. Nunca invente nomes de playlist, faixas, artistas \
ou números.
- Se precisar analisar uma playlist, chame `analisar_playlist`. A análise é \
custosa, então analise só as playlists relevantes para a pergunta.
- Os gêneros vêm de tags da comunidade do Last.fm, não do Spotify. São \
aproximados: trate-os como indício, não como verdade absoluta, e diga isso quando \
for relevante.
- Se as ferramentas não trouxerem dado suficiente para responder, diga o que \
faltou em vez de especular.

Sobre o tom: você pode ter opinião sobre música e comentar padrões interessantes \
que aparecerem nos dados, mas fundamente no que as ferramentas retornaram."""
