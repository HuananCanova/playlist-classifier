"""As ferramentas do agente — independentes de provedor.

O conteúdo de cada ferramenta mora em uma função `*_json` de módulo, que recebe
o id como argumento. Em cima delas, `build_tools()` monta a versão do chat:
ferramentas de aridade zero, com o id preso na closure. É essa amarração que dá
o escopo fixo do chat — o agente não pode pedir outra playlist porque não existe
argumento para isso.

O servidor MCP (`mcp_server.py`) chama as mesmas funções `*_json` sem essa
amarração, expondo o id como parâmetro: lá o cliente é o próprio dono da conta,
não um agente respondendo dentro de uma tela.

Assim os três consumidores — Claude, Groq e MCP — compartilham a formatação dos
dados, e só a tradução para cada protocolo muda.
"""
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from .genre_analysis import build_playlist_analysis
from .tracks import build_track_detail

MAX_TRACK_SAMPLE = 40
MAX_GENRES = 15


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., Awaitable[str]]


async def analisar_playlist_json(access_token: str, playlist_id: str) -> str:
    """Análise completa de uma playlist, serializada para o modelo."""
    try:
        analysis = await build_playlist_analysis(access_token, playlist_id)
    except httpx.HTTPStatusError as exc:
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


async def analisar_faixa_json(access_token: str, track_id: str) -> str:
    """Detalhe de uma faixa, serializado para o modelo."""
    try:
        detail = await build_track_detail(access_token, track_id)
    except httpx.HTTPStatusError as exc:
        return json.dumps(
            {
                "erro": "Não consegui ler essa faixa no Spotify "
                f"(HTTP {exc.response.status_code})."
            },
            ensure_ascii=False,
        )

    minutos = detail.duration_ms // 60000
    segundos = (detail.duration_ms % 60000) // 1000

    return json.dumps(
        {
            "faixa": detail.name,
            "artistas": detail.artists,
            "album": detail.album,
            "duracao": f"{minutos}:{segundos:02d}",
            "tags_da_faixa": detail.tags,
            "tags_do_artista": detail.artist_tags,
            "bpm": detail.bpm,
            "bpm_fonte": "Deezer" if detail.bpm else None,
            "tem_previa": bool(detail.preview_url),
            "correspondencia_deezer": detail.match_confidence,
            "titulo_deezer": detail.matched_title,
            "observacao": (
                "Tags vêm do Last.fm (aproximadas). BPM e prévia vêm do Deezer "
                "e podem faltar ou ser de uma gravação parecida, não idêntica."
            ),
        },
        ensure_ascii=False,
    )


def build_tools(
    access_token: str,
    *,
    playlist_id: str | None = None,
    track_id: str | None = None,
) -> list[Tool]:
    """Cria as ferramentas ligadas à sessão do usuário, restritas ao escopo da tela."""
    if (playlist_id is None) == (track_id is None):
        raise ValueError("Informe exatamente um escopo: playlist_id ou track_id.")

    if playlist_id is not None:

        async def analisar_esta_playlist() -> str:
            return await analisar_playlist_json(access_token, playlist_id)

        return [
            Tool(
                name="analisar_esta_playlist",
                description=(
                    "Analisa a playlist que o usuário está vendo: gêneros, "
                    "subgêneros, artistas mais frequentes e uma amostra das "
                    "faixas com suas tags. Chame antes de responder qualquer "
                    "pergunta sobre ela."
                ),
                parameters={"type": "object", "properties": {}, "required": []},
                run=analisar_esta_playlist,
            )
        ]

    async def analisar_esta_faixa() -> str:
        return await analisar_faixa_json(access_token, track_id)  # type: ignore[arg-type]

    return [
        Tool(
            name="analisar_esta_faixa",
            description=(
                "Busca os dados desta faixa: tags do Last.fm, tags do artista, "
                "BPM e metadados. Chame antes de responder qualquer pergunta sobre ela."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            run=analisar_esta_faixa,
        )
    ]


def system_prompt(*, playlist_id: str | None = None, track_id: str | None = None) -> str:
    if track_id is not None:
        return TRACK_SYSTEM_PROMPT
    if playlist_id is not None:
        return PLAYLIST_SYSTEM_PROMPT
    raise ValueError("Informe exatamente um escopo: playlist_id ou track_id.")


PLAYLIST_SYSTEM_PROMPT = """Você é o assistente do Playlist Classifier e está respondendo sobre UMA playlist específica, que o usuário tem aberta na tela.

Responda sempre em português do Brasil, de forma direta e conversacional.

Escopo — respeite rigorosamente:
- Você só pode falar sobre ESTA playlist. Não tem acesso a outras playlists, à conta inteira nem a faixas fora dela.
- Se o usuário perguntar sobre outra playlist, a coleção toda ou comparar com outras, recuse educadamente e diga que ele deve abrir aquela playlist e usar o chat dali.
- Se perguntarem sobre UMA faixa em detalhe (BPM, tags específicas, prévia), sugira abrir a página dessa faixa — lá há um chat próprio para ela.

Como trabalhar:
- Chame `analisar_esta_playlist` antes de responder qualquer coisa sobre o conteúdo dela. Nunca invente faixas, artistas ou números.
- Os gêneros vêm de tags da comunidade do Last.fm, não do Spotify. São aproximados: trate-os como indício, não como verdade absoluta.
- A análise traz uma amostra das faixas, não todas — não conclua que uma faixa não existe só porque não apareceu na amostra.

Sobre o tom: pode ter opinião sobre música e apontar padrões interessantes, mas fundamente no que a ferramenta retornou."""


TRACK_SYSTEM_PROMPT = """Você é o assistente do Playlist Classifier e está respondendo sobre UMA faixa específica, que o usuário tem aberta na tela.

Responda sempre em português do Brasil, de forma direta e conversacional.

Escopo — respeite rigorosamente:
- Você só pode falar sobre ESTA faixa. Não tem acesso a outras faixas, playlists nem à conta inteira.
- Se o usuário perguntar sobre a playlist inteira, outras músicas ou o gosto geral, recuse educadamente e diga que ele deve voltar à playlist e usar o chat dali.
- Não compare esta faixa com outras que você não possa consultar — responda só com o que a ferramenta trouxer.

Como trabalhar:
- Chame `analisar_esta_faixa` antes de responder qualquer coisa sobre ela. Nunca invente tags, BPM ou metadados.
- Tags vêm do Last.fm (aproximadas). BPM e prévia vêm do Deezer e podem faltar ou ser de uma gravação parecida — diga isso quando relevante.
- Você não ouve o áudio nem vê espectrogramas; não descreva timbre ou produção além do que tags e BPM sugerem.

Sobre o tom: pode comentar o clima ou estilo sugerido pelos dados, mas fundamente no que a ferramenta retornou."""
