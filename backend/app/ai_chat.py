"""Chat com IA sobre as playlists do usuário.

O agente não recebe os dados prontos: ele os busca através de *tools*, e é aí
que está o ponto de extensão do projeto. Busca e recomendação, mais para frente,
entram como novas tools registradas em `build_tools()` — o resto do arquivo
(streaming, sessão, rota) não muda.

Os dados do Spotify nunca entram no prompt inteiros: cada tool devolve um resumo
com teto de tamanho, para o contexto (e o custo) não crescer com o tamanho da
playlist.
"""
import json
import logging

import anthropic
import httpx
from anthropic import beta_async_tool

from .config import get_settings
from .genre_analysis import build_playlist_analysis
from .spotify_client import SpotifyClient

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5"
MAX_TOKENS = 8000

# Quantos itens cada tool devolve no máximo. Uma playlist de 500 faixas viraria
# dezenas de milhares de tokens por chamada sem esses tetos.
MAX_PLAYLISTS = 60
MAX_TRACK_SAMPLE = 40
MAX_GENRES = 15

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


class AIUnavailable(RuntimeError):
    """A chave da API da Anthropic não está configurada."""


def get_client() -> anthropic.AsyncAnthropic:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise AIUnavailable(
            "ANTHROPIC_API_KEY não configurada — adicione ao backend/.env para usar o chat."
        )
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


def build_tools(access_token: str) -> list:
    """Cria as tools ligadas à sessão do usuário.

    O token do Spotify fica capturado no closure, e não como parâmetro de tool:
    o modelo nem vê a credencial nem consegue passá-la errada. Toda tool nova
    (busca, recomendação) deve seguir esse mesmo formato.
    """

    @beta_async_tool
    async def listar_playlists() -> str:
        """Lista as playlists do usuário no Spotify.

        Retorna id, nome e número de faixas de cada playlist. Use primeiro, para
        descobrir qual playlist o usuário quer, e pegue o id para as outras
        ferramentas.
        """
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
            {"total_de_playlists": len(raw), "playlists": items},
            ensure_ascii=False,
        )

    @beta_async_tool
    async def analisar_playlist(playlist_id: str) -> str:
        """Analisa os gêneros de uma playlist específica.

        Retorna a distribuição de gêneros e subgêneros, os artistas mais
        frequentes e uma amostra das faixas com suas tags. Operação custosa
        (consulta o Spotify e o Last.fm faixa a faixa) — use só nas playlists
        relevantes para a pergunta.

        Args:
            playlist_id: O id da playlist, obtido em `listar_playlists`.
        """
        try:
            analysis = await build_playlist_analysis(access_token, playlist_id)
        except httpx.HTTPStatusError as exc:
            # Devolvido ao modelo como resultado, não levantado: assim ele explica
            # o problema ao usuário em vez de a conversa inteira morrer.
            return json.dumps(
                {"erro": f"Não consegui ler essa playlist no Spotify (HTTP {exc.response.status_code})."},
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
                    {"artista": a.label, "faixas": a.count} for a in analysis.top_artists[:10]
                ],
                "amostra_de_faixas": [
                    {
                        "faixa": t.name,
                        "artistas": t.artists,
                        "tags": t.subgenre_tags[:4],
                    }
                    for t in analysis.tracks[:MAX_TRACK_SAMPLE]
                ],
                "observacao": (
                    f"A amostra mostra {min(MAX_TRACK_SAMPLE, len(analysis.tracks))} "
                    f"de {len(analysis.tracks)} faixas."
                ),
            },
            ensure_ascii=False,
        )

    # Ponto de extensão: novas capacidades entram aqui.
    #   @beta_async_tool
    #   async def buscar_faixas(consulta: str) -> str: ...
    #   @beta_async_tool
    #   async def recomendar(...) -> str: ...
    return [listar_playlists, analisar_playlist]


async def stream_chat(access_token: str, messages: list[dict]):
    """Roda o agente e emite eventos SSE.

    Eventos:
      {"type": "tool",  "name": "..."}   — começou a usar uma ferramenta
      {"type": "text",  "delta": "..."}  — pedaço da resposta
      {"type": "done"}                   — fim
      {"type": "error", "message": "..."}
    """
    def sse(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    try:
        # Dentro do try: uma exceção aqui já está no meio do StreamingResponse,
        # então precisa virar evento de erro, não subir e cortar a resposta.
        client = get_client()
        tools = build_tools(access_token)

        runner = client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
            stream=True,
            # A conversa envolve raciocinar sobre os dados que voltam das tools,
            # então vale o thinking adaptativo.
            thinking={"type": "adaptive"},
        )

        announced: set[str] = set()
        async for stream in runner:
            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use" and block.name not in announced:
                        announced.add(block.name)
                        yield sse({"type": "tool", "name": block.name})
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta" and delta.text:
                        yield sse({"type": "text", "delta": delta.text})

        yield sse({"type": "done"})

    except AIUnavailable as exc:
        yield sse({"type": "error", "message": str(exc)})
    except anthropic.APIStatusError as exc:
        logger.error("Anthropic API error %s: %s", exc.status_code, exc.response.text[:400])
        yield sse({"type": "error", "message": f"Erro na API da Anthropic (HTTP {exc.status_code})."})
    except anthropic.APIConnectionError:
        logger.exception("Could not reach the Anthropic API")
        yield sse({"type": "error", "message": "Não consegui falar com a API da Anthropic."})
