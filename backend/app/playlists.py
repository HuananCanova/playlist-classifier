"""Routes for listing the user's playlists and analyzing one in detail."""
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request

from .auth import get_valid_access_token
from .genre_analysis import build_playlist_analysis
from .models import PlaylistAnalysis, PlaylistSummary
from .spotify_client import SpotifyClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/playlists", tags=["playlists"])


@router.get("", response_model=list[PlaylistSummary])
async def list_playlists(request: Request):
    token = await get_valid_access_token(request)
    spotify = SpotifyClient(token)

    async with httpx.AsyncClient(timeout=20.0) as client:
        raw_playlists = await spotify.get_all_playlists(client)

    return [
        PlaylistSummary(
            id=p["id"],
            name=p.get("name") or "Sem nome",
            description=p.get("description") or None,
            image=((p.get("images") or [{}])[0] or {}).get("url"),
            track_count=_track_count(p),
            owner=(p.get("owner") or {}).get("display_name"),
        )
        for p in raw_playlists
        if p is not None
    ]


def _track_count(playlist: dict) -> int:
    """Number of tracks in a playlist.

    The count moved from `tracks.total` to `items.total` in the 2026 API changes;
    `tracks` is deprecated but still sent, so fall back to it.
    """
    for key in ("items", "tracks"):
        total = (playlist.get(key) or {}).get("total")
        if total is not None:
            return total
    return 0


@router.get("/{playlist_id}/analysis", response_model=PlaylistAnalysis)
async def analyze_playlist(playlist_id: str, request: Request):
    token = await get_valid_access_token(request)
    try:
        return await build_playlist_analysis(token, playlist_id)
    except httpx.HTTPStatusError as exc:
        # Log the upstream status and body — without this, every Spotify failure looks
        # like an opaque 502 and there's nothing to debug from.
        logger.error(
            "Spotify returned %s for %s: %s",
            exc.response.status_code, exc.request.url, exc.response.text[:500],
        )
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Playlist not found") from exc
        raise HTTPException(status_code=502, detail="Spotify API error") from exc
