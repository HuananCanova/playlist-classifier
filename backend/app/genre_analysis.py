"""Combines Last.fm artist tags (broad genre) + Last.fm track tags (subgenre) into
per-track genre info, then aggregates it into playlist-level distributions.

Spotify supplies the playlist and its tracks; the genre data all comes from Last.fm
since Spotify removed the `genres` field from artist objects in its 2026 API changes.
"""
import asyncio
import logging
import time
from collections import Counter

import httpx

from .lastfm_client import get_artist_tags, get_track_tags
from .models import GenreCount, PlaylistAnalysis, PlaylistSummary, TrackGenreInfo
from .spotify_client import SpotifyClient, gather_with_concurrency

logger = logging.getLogger(__name__)

# One Last.fm request per track and per artist, so concurrency sets the wall time.
# Measured against the live API with 60 lookups: 8 -> 1.69s, 16 -> 1.22s, 24 -> 1.08s,
# 32 -> 0.74s, with zero 429s throughout. 24 takes most of the win while leaving
# headroom; a throttled lookup degrades to "no tags" rather than failing the request.
LASTFM_CONCURRENCY = 24

# The default keepalive pool (20) would throttle the two pools above; size it to fit
# both the artist and the track pass running at once.
HTTP_LIMITS = httpx.Limits(max_connections=64, max_keepalive_connections=64)


async def build_playlist_analysis(
    access_token: str, playlist_id: str
) -> PlaylistAnalysis:
    spotify = SpotifyClient(access_token)

    async with httpx.AsyncClient(timeout=20.0, limits=HTTP_LIMITS) as client:
        spotify_started = time.perf_counter()
        playlist_data, tracks = await asyncio.gather(
            spotify.get_playlist(client, playlist_id),
            spotify.get_all_playlist_tracks(client, playlist_id),
        )
        spotify_seconds = time.perf_counter() - spotify_started

        # Last.fm is keyed by name, not by Spotify id.
        artist_names = sorted(
            {a["name"] for t in tracks for a in (t.get("artists") or []) if a and a.get("name")}
        )

        async def genre_for(artist_name: str) -> tuple[str, list[str]]:
            return artist_name, await get_artist_tags(client, artist_name)

        async def tags_for(track: dict) -> list[str]:
            primary_artist = ((track.get("artists") or [{}])[0] or {}).get("name") or ""
            return await get_track_tags(client, primary_artist, track.get("name") or "")

        lastfm_started = time.perf_counter()
        artist_genre_pairs, all_tags = await asyncio.gather(
            gather_with_concurrency(LASTFM_CONCURRENCY, *(genre_for(n) for n in artist_names)),
            gather_with_concurrency(LASTFM_CONCURRENCY, *(tags_for(t) for t in tracks)),
        )
        artist_genres = dict(artist_genre_pairs)
        lastfm_seconds = time.perf_counter() - lastfm_started

    logger.info(
        "Analysed %s: %d tracks / %d artists — Spotify %.2fs, Last.fm %.2fs",
        playlist_id, len(tracks), len(artist_names), spotify_seconds, lastfm_seconds,
    )

    track_infos: list[TrackGenreInfo] = []
    genre_counter: Counter = Counter()
    subgenre_counter: Counter = Counter()
    artist_counter: Counter = Counter()
    missing_genre = 0

    for track, lastfm_tags in zip(tracks, all_tags):
        track_artist_names = [
            a["name"] for a in (track.get("artists") or []) if a and a.get("name")
        ]
        track_genres: list[str] = []
        for name in track_artist_names:
            track_genres.extend(artist_genres.get(name, []))
        track_genres = sorted(set(track_genres))

        subgenre_tags = sorted(set(lastfm_tags) | set(track_genres))

        if not track_genres and not lastfm_tags:
            missing_genre += 1

        for g in track_genres:
            genre_counter[g] += 1
        for t in subgenre_tags:
            subgenre_counter[t] += 1
        for name in track_artist_names:
            artist_counter[name] += 1

        album = track.get("album") or {}
        images = album.get("images") or []
        urls = track.get("external_urls") or {}

        track_infos.append(
            TrackGenreInfo(
                track_id=track["id"],
                name=track.get("name") or "(sem título)",
                artists=track_artist_names,
                album=album.get("name"),
                image=images[0]["url"] if images else None,
                duration_ms=track.get("duration_ms") or 0,
                popularity=track.get("popularity"),
                genres=track_genres,
                subgenre_tags=subgenre_tags,
                preview_url=track.get("preview_url"),
                spotify_url=urls.get("spotify"),
            )
        )

    playlist_images = playlist_data.get("images") or []
    summary = PlaylistSummary(
        id=playlist_data["id"],
        name=playlist_data.get("name") or "Sem nome",
        description=playlist_data.get("description") or None,
        image=playlist_images[0]["url"] if playlist_images else None,
        track_count=len(track_infos),
        owner=(playlist_data.get("owner") or {}).get("display_name"),
    )

    def top_counts(counter: Counter, limit: int = 25) -> list[GenreCount]:
        return [GenreCount(label=label, count=count) for label, count in counter.most_common(limit)]

    return PlaylistAnalysis(
        playlist=summary,
        tracks=track_infos,
        genre_distribution=top_counts(genre_counter),
        subgenre_distribution=top_counts(subgenre_counter),
        top_artists=top_counts(artist_counter, limit=15),
        tracks_missing_genre=missing_genre,
    )
