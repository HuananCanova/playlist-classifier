"""Chat com IA sobre as playlists — seleção de provedor e adaptador do Claude.

O agente não recebe os dados prontos: ele os busca através das ferramentas de
`ai_tools.py`. Este arquivo traduz essas ferramentas para a API do Claude e
transforma o que o agente produz em eventos SSE.

Dois provedores: Claude (`claude-opus-5`) é o alvo real; Groq existe para testar
sem custo. Ambos emitem os mesmos eventos, então o frontend não muda.
"""
import asyncio
import json
import logging

import anthropic
from anthropic import beta_async_tool

from .ai_tools import PLAYLIST_SYSTEM_PROMPT, SYSTEM_PROMPT, build_tools
from .config import get_settings

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5"
MAX_TOKENS = 8000

_DONE = object()  # sentinela: o agente terminou


class AIUnavailable(RuntimeError):
    """Nenhum provedor de IA está configurado."""


def active_provider() -> str | None:
    """Qual provedor está utilizável agora, ou None se nenhum tiver chave."""
    settings = get_settings()
    provider = (settings.chat_provider or "anthropic").lower()

    if provider == "groq":
        return "groq" if settings.groq_api_key else None
    return "anthropic" if settings.anthropic_api_key else None


def _anthropic_tools(access_token: str, playlist_id: str | None) -> list:
    """Traduz as ferramentas neutras para o formato do SDK da Anthropic.

    O schema vem do registro em vez da inferência por assinatura, então as duas
    APIs enxergam exatamente os mesmos argumentos.
    """
    tools = []
    for tool in build_tools(access_token, playlist_id):

        async def call(_run=tool.run, **kwargs) -> str:
            return await _run(**kwargs)

        tools.append(
            beta_async_tool(
                call,
                name=tool.name,
                description=tool.description,
                input_schema=tool.parameters,
            )
        )
    return tools


async def _run_anthropic(
    access_token: str, messages: list[dict], emit, playlist_id: str | None
) -> None:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=PLAYLIST_SYSTEM_PROMPT if playlist_id else SYSTEM_PROMPT,
        tools=_anthropic_tools(access_token, playlist_id),
        messages=messages,
        stream=True,
        # A conversa envolve raciocinar sobre os dados que voltam das ferramentas.
        thinking={"type": "adaptive"},
    )

    async for stream in runner:
        async for event in stream:
            if event.type == "content_block_start":
                block = event.content_block
                if block.type == "tool_use":
                    await emit({"type": "tool", "name": block.name})
            elif event.type == "content_block_delta":
                delta = event.delta
                if delta.type == "text_delta" and delta.text:
                    await emit({"type": "text", "delta": delta.text})


async def stream_chat(
    access_token: str, messages: list[dict], playlist_id: str | None = None
):
    """Roda o agente e emite eventos SSE conforme eles acontecem.

    O agente roda numa task própria e publica numa fila; este gerador consome a
    fila. Sem isso o texto só chegaria ao navegador no fim, que é justamente o
    que o streaming existe para evitar.

    Eventos:
      {"type": "tool",  "name": "..."}   — começou a usar uma ferramenta
      {"type": "text",  "delta": "..."}  — pedaço da resposta
      {"type": "done"}                   — fim
      {"type": "error", "message": "..."}
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(payload: dict) -> None:
        await queue.put(payload)

    async def run() -> None:
        try:
            provider = active_provider()
            if provider is None:
                raise AIUnavailable(
                    "Nenhuma chave de IA configurada — defina ANTHROPIC_API_KEY "
                    "(ou GROQ_API_KEY com CHAT_PROVIDER=groq) no backend/.env."
                )

            if provider == "groq":
                from .ai_chat_groq import stream_chat as run_groq

                await run_groq(access_token, messages, emit, playlist_id)
            else:
                await _run_anthropic(access_token, messages, emit, playlist_id)

        except AIUnavailable as exc:
            await queue.put({"type": "error", "message": str(exc)})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Chat failed")
            await queue.put(
                {"type": "error", "message": "O chat falhou. Veja o log do backend."}
            )
        finally:
            await queue.put(_DONE)

    task = asyncio.create_task(run())
    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    finally:
        # O cliente pode desconectar no meio; não deixe o agente rodando (e
        # cobrando) sozinho.
        if not task.done():
            task.cancel()
