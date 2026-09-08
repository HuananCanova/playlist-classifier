"""Pydantic response models shared across routes."""
from pydantic import BaseModel


class PlaylistSummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    image: str | None = None
    track_count: int
    owner: str | None = None


class TrackGenreInfo(BaseModel):
    track_id: str
    name: str
    artists: list[str]
    album: str | None = None
    image: str | None = None
    duration_ms: int
    popularity: int | None = None
    genres: list[str]
    subgenre_tags: list[str]
    # BPM e prévia vêm do Deezer: o Spotify cortou audio-features e preview_url
    # para apps criados depois de 27/11/2024. None = o Deezer não sabe.
    bpm: float | None = None
    preview_url: str | None = None
    deezer_url: str | None = None
    spotify_url: str | None = None


class GenreCount(BaseModel):
    label: str
    count: int


class PlaylistAnalysis(BaseModel):
    playlist: PlaylistSummary
    tracks: list[TrackGenreInfo]
    genre_distribution: list[GenreCount]
    subgenre_distribution: list[GenreCount]
    top_artists: list[GenreCount]
    bpm_histogram: list[GenreCount]
    average_bpm: float | None = None
    tracks_missing_genre: int
    tracks_missing_bpm: int = 0
