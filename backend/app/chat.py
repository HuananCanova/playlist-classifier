"""Rota do chat com IA."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .ai_chat import stream_chat
from .auth import get_valid_access_token
from .config import get_settings

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Teto de histórico: a conversa inteira é reenviada a cada turno, então sem
# limite o custo cresce sem parar numa sessão longa.
MAX_HISTORY = 20


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_HISTORY)


@router.get("/status")
async def chat_status():
    """Diz ao frontend se o chat está disponível, para ele esconder a UI se não estiver."""
    return {"available": bool(get_settings().anthropic_api_key)}


@router.post("")
async def chat(payload: ChatRequest, request: Request):
    token = await get_valid_access_token(request)

    if not get_settings().anthropic_api_key:
        raise HTTPException(
            status_code=503,
            detail="Chat indisponível: configure ANTHROPIC_API_KEY no backend/.env.",
        )

    messages = [{"role": m.role, "content": m.content} for m in payload.messages]

    return StreamingResponse(
        stream_chat(token, messages),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # impede buffering em proxies, que mataria o streaming
        },
    )
