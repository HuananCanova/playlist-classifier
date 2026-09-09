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
    preview_url: str | None = None
    spotify_url: str | None = None


class TrackDetail(BaseModel):
    track_id: str
    name: str
    artists: list[str]
    album: str | None = None
    image: str | None = None
    duration_ms: int
    spotify_url: str | None = None
    tags: list[str] = []
    artist_tags: list[str] = []
    # Vêm do Deezer e podem faltar: BPM só existe em ~43% das faixas, e o
    # preview em ~93%.
    bpm: float | None = None
    preview_url: str | None = None
    deezer_url: str | None = None
    match_confidence: str | None = None
    matched_title: str | None = None


class GenreCount(BaseModel):
    label: str
    count: int


class PlaylistAnalysis(BaseModel):
    playlist: PlaylistSummary
    tracks: list[TrackGenreInfo]
    genre_distribution: list[GenreCount]
    subgenre_distribution: list[GenreCount]
    top_artists: list[GenreCount]
    tracks_missing_genre: int
