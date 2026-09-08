"""FastAPI app entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .auth import router as auth_router
from .chat import router as chat_router
from .config import get_settings
from .playlists import router as playlists_router

settings = get_settings()

app = FastAPI(title="Playlist Classifier API")

# Signed, httpOnly session cookie holding the Spotify tokens (see auth.py).
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=False,  # set True once this runs behind HTTPS
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
app.include_router(chat_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
