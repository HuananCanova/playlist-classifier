"""Rota do chat com IA."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

import httpx

from .ai_chat import active_provider, stream_chat
from .auth import get_valid_access_token
from .metrics import recent, summary
from .playlists import _spotify_error, account_track_ids, analysis_for_user

router = APIRouter(prefix="/api/chat", tags=["chat"])

MAX_HISTORY = 20


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_HISTORY)
    playlist_id: str | None = Field(default=None, max_length=64)
    track_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def exactly_one_scope(self) -> "ChatRequest":
        has_playlist = self.playlist_id is not None
        has_track = self.track_id is not None
        if has_playlist == has_track:
            raise ValueError("Informe exatamente um escopo: playlist_id ou track_id.")
        return self


@router.get("/status")
async def chat_status():
    provider = active_provider()
    return {"available": provider is not None, "provider": provider}


@router.get("/metrics")
async def chat_metrics(request: Request, limit: int = 50):
    """Custo e latência dos últimos turnos, agregados por provedor.

    Existe para que a escolha entre Claude e Groq seja um número em vez de uma
    impressão. Fica em memória: reiniciar o backend zera.
    """
    await get_valid_access_token(request)
    return {"resumo": summary(), "turnos": recent(limit)}


@router.post("")
async def chat(payload: ChatRequest, request: Request):
    token = await get_valid_access_token(request)

    if active_provider() is None:
        raise HTTPException(
            status_code=503,
            detail="Chat indisponível: configure ANTHROPIC_API_KEY ou GROQ_API_KEY no backend/.env.",
        )

    if payload.playlist_id is not None:
        # As ferramentas do agente leem a análise pelo id. Resolver aqui confere
        # que esta conta pode ver a playlist (listagem ou 403 do Spotify) antes
        # de o agente tocar nela, e deixa a análise quente no cache para elas.
        try:
            await analysis_for_user(request, payload.playlist_id)
        except httpx.HTTPStatusError as exc:
            raise _spotify_error(exc) from exc

    messages = [{"role": m.role, "content": m.content} for m in payload.messages]

    return StreamingResponse(
        stream_chat(
            token,
            messages,
            playlist_id=payload.playlist_id,
            track_id=payload.track_id,
            # Faixas parecidas só dentro do acervo desta conta.
            account_track_ids=await account_track_ids(request) if payload.track_id else None,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
