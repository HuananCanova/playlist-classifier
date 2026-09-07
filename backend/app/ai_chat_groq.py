"""Adaptador Groq — usado para testar o chat sem custo.

O Groq expõe uma API compatível com OpenAI (`/openai/v1`), não com a Anthropic:
formato de mensagens, de tool calling e de streaming são os da OpenAI. Por isso
este é um laço próprio, e não uma troca de `base_url` sobre o código do Claude.

As ferramentas vêm prontas de `ai_tools.py`, então só a tradução mora aqui.
"""
import json
import logging

from openai import AsyncOpenAI

from .ai_tools import SYSTEM_PROMPT, Tool, build_tools
from .config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.groq.com/openai/v1"
MAX_TOKENS = 4000

# Teto de voltas do laço: sem ele, um modelo que insista em chamar ferramentas
# ficaria girando (e cobrando) indefinidamente.
MAX_ITERATIONS = 6


def _to_openai_schema(tool: Tool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


async def stream_chat(access_token: str, messages: list[dict], emit):
    """Roda o agente no Groq, emitindo eventos pelo callback `emit`.

    `emit` recebe os mesmos dicionários que o adaptador do Claude emite, então o
    frontend não sabe (nem precisa saber) qual provedor respondeu.
    """
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.groq_api_key, base_url=BASE_URL)

    tools = {t.name: t for t in build_tools(access_token)}
    schemas = [_to_openai_schema(t) for t in tools.values()]

    convo = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]

    for _ in range(MAX_ITERATIONS):
        stream = await client.chat.completions.create(
            model=settings.groq_model,
            messages=convo,
            tools=schemas,
            max_tokens=MAX_TOKENS,
            stream=True,
        )

        text_parts: list[str] = []
        # As tool calls chegam fatiadas nos deltas; monta por índice.
        pending: dict[int, dict] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                text_parts.append(delta.content)
                await emit({"type": "text", "delta": delta.content})

            for call in delta.tool_calls or []:
                slot = pending.setdefault(
                    call.index, {"id": "", "name": "", "arguments": ""}
                )
                if call.id:
                    slot["id"] = call.id
                if call.function and call.function.name:
                    slot["name"] = call.function.name
                    await emit({"type": "tool", "name": call.function.name})
                if call.function and call.function.arguments:
                    slot["arguments"] += call.function.arguments

        if not pending:
            return  # o modelo respondeu sem pedir mais nada

        convo.append(
            {
                "role": "assistant",
                "content": "".join(text_parts) or None,
                "tool_calls": [
                    {
                        "id": slot["id"],
                        "type": "function",
                        "function": {"name": slot["name"], "arguments": slot["arguments"] or "{}"},
                    }
                    for slot in pending.values()
                ],
            }
        )

        for slot in pending.values():
            tool = tools.get(slot["name"])
            if tool is None:
                result = json.dumps({"erro": f"Ferramenta desconhecida: {slot['name']}"})
            else:
                try:
                    args = json.loads(slot["arguments"] or "{}")
                    result = await tool.run(**args)
                except (json.JSONDecodeError, TypeError) as exc:
                    # Argumentos malformados voltam como resultado para o modelo
                    # corrigir, em vez de derrubar a conversa.
                    result = json.dumps({"erro": f"Argumentos inválidos: {exc}"}, ensure_ascii=False)

            convo.append(
                {"role": "tool", "tool_call_id": slot["id"], "content": result}
            )

    logger.warning("Groq chat hit the %d-iteration cap", MAX_ITERATIONS)
    await emit(
        {
            "type": "error",
            "message": "A conversa passou do limite de chamadas de ferramenta. Tente uma pergunta mais específica.",
        }
    )
