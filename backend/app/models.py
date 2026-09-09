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


class ClusterInfo(BaseModel):
    """Um grupo de faixas com clima parecido dentro de uma playlist."""

    id: int
    label: str
    size: int
    top_tags: list[str] = []
    track_ids: list[str] = []
    sample_tracks: list[str] = []


class ClusterPoint(BaseModel):
    """Uma faixa projetada em 2D, só para o gráfico."""

    track_id: str
    x: float
    y: float
    cluster: int


class PlaylistClusters(BaseModel):
    clusters: list[ClusterInfo] = []
    k: int
    # Média da silhueta do agrupamento escolhido: acima de ~0,25 os grupos são
    # razoavelmente separados; perto de 0 eles se sobrepõem.
    silhouette: float | None = None
    points: list[ClusterPoint] = []
    # Preenchido quando não deu para agrupar — a playlist é curta demais, ou as
    # faixas não compartilham tags suficientes.
    note: str | None = None


class SearchHit(BaseModel):
    """Uma faixa devolvida pela busca semântica."""

    track_id: str
    nome: str
    artistas: list[str] = []
    album: str | None = None
    tags: list[str] = []
    # 1.0 = idêntico. É `1 - distância cosseno`, então pode ser levemente
    # negativo para pares de sentidos opostos.
    similaridade: float


class SearchStatus(BaseModel):
    indexed_tracks: int
    # `None` quando o Spotify não respondeu — o frontend distingue isso de zero.
    total_playlists: int | None = None
    indexed_playlists: int | None = None
    pending_playlists: int | None = None


class IndexStatus(BaseModel):
    """Progresso da varredura que alimenta o índice."""

    running: bool
    total: int
    done: int
    indexed_tracks: int
    current: str | None = None
    errors: list[str] = []
    started_at: float | None = None
    finished_at: float | None = None
    waiting_seconds: float | None = None


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
