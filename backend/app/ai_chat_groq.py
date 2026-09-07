"""Adaptador Groq — usado para testar o chat sem custo.

O Groq expõe uma API compatível com OpenAI (`/openai/v1`), não com a Anthropic:
formato de mensagens, de tool calling e de streaming são os da OpenAI. Por isso
este é um laço próprio, e não uma troca de `base_url` sobre o código do Claude.

As ferramentas vêm prontas de `ai_tools.py`, então só a tradução mora aqui.
"""
import asyncio
import json
import logging

from openai import AsyncOpenAI

from .ai_tools import PLAYLIST_SYSTEM_PROMPT, SYSTEM_PROMPT, Tool, build_tools
from .config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.groq.com/openai/v1"
MAX_TOKENS = 4000

# Teto de voltas do laço: sem ele, um modelo que insista em chamar ferramentas
# ficaria girando (e cobrando) indefinidamente. Perguntas amplas gastam uma
# volta por playlist, então 6 era apertado demais.
MAX_ITERATIONS = 10


def _to_openai_schema(tool: Tool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


async def stream_chat(
    access_token: str, messages: list[dict], emit, playlist_id: str | None = None
):
    """Roda o agente no Groq, emitindo eventos pelo callback `emit`.

    `emit` recebe os mesmos dicionários que o adaptador do Claude emite, então o
    frontend não sabe (nem precisa saber) qual provedor respondeu.
    """
    settings = get_settings()

    tools = {t.name: t for t in build_tools(access_token, playlist_id)}
    schemas = [_to_openai_schema(t) for t in tools.values()]

    prompt = PLAYLIST_SYSTEM_PROMPT if playlist_id else SYSTEM_PROMPT
    convo = [{"role": "system", "content": prompt}, *messages]

    # Resultados já entregues nesta conversa. Modelos menores às vezes repetem a
    # mesma chamada em looping; devolver o resultado com um aviso é mais barato
    # (e mais útil ao modelo) do que rodar a análise de novo.
    served: dict[str, str] = {}

    async with AsyncOpenAI(api_key=settings.groq_api_key, base_url=BASE_URL) as client:
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

            # `async with` fecha a resposta HTTP ao fim de cada volta; sem isso o
            # stream só é liberado no coletor de lixo, que reclama no shutdown.
            async with stream:
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
                            "function": {
                                "name": slot["name"],
                                "arguments": slot["arguments"] or "{}",
                            },
                        }
                        for slot in pending.values()
                    ],
                }
            )

            async def execute(slot: dict) -> tuple[str, str]:
                signature = f"{slot['name']}:{slot['arguments']}"
                tool = tools.get(slot["name"])

                if signature in served:
                    return slot["id"], json.dumps(
                        {
                            "aviso": "Esta chamada já foi feita nesta conversa; "
                            "abaixo está o mesmo resultado. Responda ao usuário "
                            "com o que já tem em vez de chamar de novo.",
                            "resultado": served[signature],
                        },
                        ensure_ascii=False,
                    )
                if tool is None:
                    return slot["id"], json.dumps(
                        {"erro": f"Ferramenta desconhecida: {slot['name']}"},
                        ensure_ascii=False,
                    )
                try:
                    args = json.loads(slot["arguments"] or "{}")
                    result = await tool.run(**args)
                    served[signature] = result
                    return slot["id"], result
                except (json.JSONDecodeError, TypeError) as exc:
                    # Argumentos malformados voltam como resultado para o modelo
                    # corrigir, em vez de derrubar a conversa.
                    return slot["id"], json.dumps(
                        {"erro": f"Argumentos inválidos: {exc}"}, ensure_ascii=False
                    )

            # Em paralelo: analisar várias playlists é o caso comum, e cada uma
            # leva segundos. Em série isso estourava o tempo e o teto de voltas.
            results = await asyncio.gather(*(execute(s) for s in pending.values()))
            for call_id, result in results:
                convo.append({"role": "tool", "tool_call_id": call_id, "content": result})

        # Teto atingido: em vez de desistir, peça a resposta final sem ferramentas,
        # para o usuário receber uma conclusão do que já foi levantado.
        logger.warning("Groq chat hit the %d-iteration cap; asking for a wrap-up", MAX_ITERATIONS)
        convo.append(
            {
                "role": "system",
                "content": "Você atingiu o limite de chamadas de ferramenta. "
                "Responda agora ao usuário com o que já levantou, deixando claro "
                "que a resposta se baseia nas playlists analisadas até aqui.",
            }
        )
        async with await client.chat.completions.create(
            model=settings.groq_model,
            messages=convo,
            max_tokens=MAX_TOKENS,
            stream=True,
        ) as stream:
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    await emit({"type": "text", "delta": chunk.choices[0].delta.content})
