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

from .clustering import cluster_playlist
from .genre_analysis import build_playlist_analysis
from .tracks import build_track_detail
from .vector_store import search as vector_search
from .vector_store import similar_to_track

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


MAX_BUSCA = 12


def _resumir_hits(hits: list[dict]) -> list[dict]:
    return [
        {
            "faixa": h["nome"],
            "artistas": h["artistas"],
            "tags": h["tags"][:5],
            "similaridade": h["similaridade"],
        }
        for h in hits
    ]


async def buscar_na_playlist_json(access_token: str, playlist_id: str, consulta: str) -> str:
    """Busca semântica restrita às faixas de uma playlist.

    O recorte vem dos ids da própria análise, então a ferramenta não consegue
    vazar faixas de fora do escopo da conversa nem que o modelo peça.
    """
    try:
        analysis = await build_playlist_analysis(access_token, playlist_id)
    except httpx.HTTPStatusError as exc:
        return json.dumps(
            {"erro": f"Não consegui ler essa playlist (HTTP {exc.response.status_code})."},
            ensure_ascii=False,
        )

    ids = [t.track_id for t in analysis.tracks]
    hits = await vector_search(consulta, limite=MAX_BUSCA, track_ids=ids)

    if not hits:
        return json.dumps(
            {
                "resultados": [],
                "observacao": (
                    "Nada no índice para esta playlist ainda. O índice é montado "
                    "quando a playlist é analisada — se a análise acabou de rodar, "
                    "vale tentar de novo em alguns segundos."
                ),
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "consulta": consulta,
            "resultados": _resumir_hits(hits),
            "observacao": (
                "Ordenado por proximidade semântica entre a consulta e as tags "
                "da faixa, não por correspondência exata de palavra. Similaridade "
                "perto de 1 é forte; abaixo de ~0,2 é fraca e provavelmente não "
                "responde à pergunta."
            ),
        },
        ensure_ascii=False,
    )


async def grupos_da_playlist_json(access_token: str, playlist_id: str) -> str:
    """Grupos de clima da playlist, calculados por k-means sobre as tags."""
    try:
        analysis = await build_playlist_analysis(access_token, playlist_id)
    except httpx.HTTPStatusError as exc:
        return json.dumps(
            {"erro": f"Não consegui ler essa playlist (HTTP {exc.response.status_code})."},
            ensure_ascii=False,
        )

    resultado = await cluster_playlist(analysis)
    if not resultado.clusters:
        return json.dumps({"grupos": [], "observacao": resultado.note}, ensure_ascii=False)

    return json.dumps(
        {
            "quantidade_de_grupos": resultado.k,
            "silhueta": resultado.silhouette,
            "grupos": [
                {
                    "tags_que_distinguem": c.top_tags,
                    "faixas": c.size,
                    "exemplos": c.sample_tracks,
                }
                for c in resultado.clusters
            ],
            "observacao": (
                "Grupos vêm de k-means sobre as tags, não de um julgamento "
                "editorial: as `tags_que_distinguem` são as que mais separam o "
                "grupo do resto da playlist. Use-as para dar um nome em português "
                "a cada grupo. A silhueta mede o quanto os grupos se separam — "
                "acima de 0,25 é razoável, perto de 0 eles se sobrepõem e vale "
                "dizer que a divisão é fraca."
            ),
        },
        ensure_ascii=False,
    )


async def faixas_parecidas_json(track_id: str, track_ids: list[str] | None = None) -> str:
    """Vizinhos semânticos de uma faixa, dentro do acervo já indexado.

    `track_ids` limita os vizinhos ao acervo de uma conta (o chat sempre passa;
    o servidor MCP, local e de uma pessoa só, usa o índice inteiro)."""
    hits = await similar_to_track(track_id, limite=8, track_ids=track_ids)

    if not hits:
        return json.dumps(
            {
                "resultados": [],
                "observacao": (
                    "Esta faixa ainda não está no índice, ou não há outras faixas "
                    "indexadas para comparar. O índice cresce conforme as playlists "
                    "são analisadas."
                ),
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "resultados": _resumir_hits(hits),
            "observacao": (
                "São as faixas mais próximas DENTRO do que o usuário já analisou "
                "neste app — não é uma recomendação sobre todo o catálogo do "
                "Spotify. Deixe isso claro na resposta."
            ),
        },
        ensure_ascii=False,
    )


def build_tools(
    access_token: str,
    *,
    playlist_id: str | None = None,
    track_id: str | None = None,
    account_track_ids: list[str] | None = None,
) -> list[Tool]:
    """Cria as ferramentas ligadas à sessão do usuário, restritas ao escopo da tela.

    `account_track_ids` são as faixas da conta: o limite de `faixas_parecidas`
    dentro do índice, que é compartilhado entre contas."""
    if (playlist_id is None) == (track_id is None):
        raise ValueError("Informe exatamente um escopo: playlist_id ou track_id.")

    if playlist_id is not None:

        async def analisar_esta_playlist() -> str:
            return await analisar_playlist_json(access_token, playlist_id)

        async def buscar_nesta_playlist(consulta: str) -> str:
            return await buscar_na_playlist_json(access_token, playlist_id, consulta)

        async def grupos_desta_playlist() -> str:
            return await grupos_da_playlist_json(access_token, playlist_id)

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
            ),
            Tool(
                name="buscar_nesta_playlist",
                description=(
                    "Busca faixas DESTA playlist por descrição livre — clima, "
                    "textura, instrumento, energia — em vez de nome exato. Use "
                    "quando a pergunta for do tipo 'quais faixas são mais X', com "
                    "X sendo algo que não é uma tag literal. A busca é semântica: "
                    "'melancólico' encontra faixas marcadas como sad, wistful ou "
                    "dream pop, mesmo sem essa palavra aparecer."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "consulta": {
                            "type": "string",
                            "description": "A descrição a procurar, em poucas palavras.",
                        }
                    },
                    "required": ["consulta"],
                },
                run=buscar_nesta_playlist,
            ),
            Tool(
                name="grupos_desta_playlist",
                description=(
                    "Separa as faixas da playlist em grupos de clima parecido "
                    "(k-means sobre as tags) e devolve as tags que distinguem "
                    "cada grupo. Use quando perguntarem se a playlist é coesa, "
                    "se tem 'partes' ou 'fases', ou como ela poderia ser dividida."
                ),
                parameters={"type": "object", "properties": {}, "required": []},
                run=grupos_desta_playlist,
            ),
        ]

    async def analisar_esta_faixa() -> str:
        return await analisar_faixa_json(access_token, track_id)  # type: ignore[arg-type]

    async def faixas_parecidas() -> str:
        return await faixas_parecidas_json(track_id, account_track_ids)  # type: ignore[arg-type]

    return [
        Tool(
            name="analisar_esta_faixa",
            description=(
                "Busca os dados desta faixa: tags do Last.fm, tags do artista, "
                "BPM e metadados. Chame antes de responder qualquer pergunta sobre ela."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            run=analisar_esta_faixa,
        ),
        Tool(
            name="faixas_parecidas",
            description=(
                "Encontra faixas parecidas com esta entre as que o usuário já "
                "analisou no app. Use quando perguntarem o que ouvir depois, com "
                "o que esta faixa se parece, ou onde ela se encaixa no acervo."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            run=faixas_parecidas,
        ),
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
- Para perguntas sobre clima, textura ou energia — “quais faixas são mais dançantes”, “o que aqui é melancólico” — use `buscar_nesta_playlist`. A contagem de tags responde “quantas são shoegaze”; a busca semântica responde “quais soam etéreas”, que não é uma tag.
- Os gêneros vêm de tags da comunidade do Last.fm, não do Spotify. São aproximados: trate-os como indício, não como verdade absoluta.
- A análise traz uma amostra das faixas, não todas — não conclua que uma faixa não existe só porque não apareceu na amostra.

Sobre o tom: pode ter opinião sobre música e apontar padrões interessantes, mas fundamente no que a ferramenta retornou."""


TRACK_SYSTEM_PROMPT = """Você é o assistente do Playlist Classifier e está respondendo sobre UMA faixa específica, que o usuário tem aberta na tela.

Responda sempre em português do Brasil, de forma direta e conversacional.

Escopo — respeite rigorosamente:
- O assunto é ESTA faixa. Você não tem acesso à conta inteira nem consegue abrir outra playlist.
- Há uma exceção deliberada: `faixas_parecidas` devolve faixas semelhantes a esta dentro do que o usuário já analisou no app. Use para recomendar ou situar a faixa, e deixe claro que a comparação é com o acervo já analisado, não com o catálogo do Spotify.
- Se perguntarem sobre a playlist inteira ou o gosto geral, recuse educadamente e diga que ele deve voltar à playlist e usar o chat dali.
- Fora o que as ferramentas trouxerem, não compare esta faixa com outras.

Como trabalhar:
- Chame `analisar_esta_faixa` antes de responder qualquer coisa sobre ela. Nunca invente tags, BPM ou metadados.
- Tags vêm do Last.fm (aproximadas). BPM e prévia vêm do Deezer e podem faltar ou ser de uma gravação parecida — diga isso quando relevante.
- Você não ouve o áudio nem vê espectrogramas; não descreva timbre ou produção além do que tags e BPM sugerem.

Sobre o tom: pode comentar o clima ou estilo sugerido pelos dados, mas fundamente no que a ferramenta retornou."""
