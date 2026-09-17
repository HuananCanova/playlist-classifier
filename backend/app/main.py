"""FastAPI app entrypoint."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, sessions
from .auth import router as auth_router
from .chat import router as chat_router
from .config import get_settings
from .playlists import router as playlists_router
from .profile import router as profile_router
from .search import router as search_router
from .tracks import router as tracks_router
from .spotify_client import throttle_state

settings = get_settings()
sessions.check_settings(settings)



@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Abre o banco e aplica as migrações na subida: um volume sem permissão de
    # escrita ou uma migração quebrada aparecem no deploy, não na primeira visita.
    await asyncio.to_thread(db.query, "SELECT 1")
    removed = await asyncio.to_thread(sessions.delete_expired)
    if removed:
        logging.getLogger(__name__).info("Removidas %d sessões expiradas", removed)
    yield
    db.close()


app = FastAPI(title="Playlist Classifier API", lifespan=lifespan)

# Sessão no servidor: o cookie leva só um id opaco; os tokens do Spotify ficam
# no banco, criptografados (sessions.py).
app.add_middleware(
    sessions.ServerSessionMiddleware,
    secure=settings.session_cookie_secure,
    same_site=settings.session_cookie_samesite,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Retry-After não está na lista segura do CORS: sem expor explicitamente, o
    # navegador esconde o cabeçalho e o front não consegue dizer quanto falta.
    expose_headers=["Retry-After"],
)

app.include_router(auth_router)
app.include_router(playlists_router)
app.include_router(profile_router)
app.include_router(tracks_router)
app.include_router(search_router)
app.include_router(chat_router)


@app.get("/api/health")
async def health():
    # `spotify_throttled` mostra os segundos restantes por endpoint bloqueado.
    # Sem isso, um 429 longo só aparece como erro na tela, sem forma de saber
    # quanto falta nem se já passou.
    return {"status": "ok", "spotify_throttled": throttle_state()}
