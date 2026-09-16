"""Pydantic response models shared across routes."""
from pydantic import BaseModel


class PlaylistSummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    image: str | None = None
    track_count: int
    owner: str | None = None
    # Muda a cada alteração no conteúdo: é o que diz se um resumo guardado em
    # disco ainda vale (profile_store.py).
    snapshot_id: str | None = None


class TrackGenreInfo(BaseModel):
    track_id: str
    name: str
    artists: list[str]
    # Ids do Spotify na mesma ordem de `artists`. Já vinham na resposta das
    # faixas e eram descartados; são o que liga cada nome à página do artista,
    # sem uma busca por nome (que erra em nomes repetidos).
    artist_ids: list[str] = []
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
    # Alimentam o perfil. Todos opcionais: vêm de campos que o Spotify já
    # tirou de outros objetos, e a ausência não pode derrubar a análise.
    added_at: str | None = None
    release_year: int | None = None
    explicit: bool | None = None


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
    # Chamadas ao Spotify que indexar o que falta custaria — para decidir antes.
    estimated_calls: int | None = None
    # Segundos até o fim de uma suspensão do Spotify, se houver.
    blocked_seconds: float | None = None


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
    blocked_seconds: float | None = None


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


class ArtistTrack(BaseModel):
    """Uma faixa do artista, para as listas da página dele.

    Vem de duas origens: do acervo (id do Spotify, abre a página da faixa) ou
    das mais tocadas no Deezer (sem id do Spotify, mas com prévia tocável).
    """

    track_id: str | None = None
    name: str
    album: str | None = None
    image: str | None = None
    spotify_url: str | None = None
    preview_url: str | None = None
    deezer_url: str | None = None
    # Só nas faixas que vieram do acervo do usuário: onde ela está.
    playlist_id: str | None = None
    playlist_name: str | None = None


class SimilarArtist(BaseModel):
    name: str
    # O Last.fm dá o nome e o link dele; o id do Spotify sai de uma busca por
    # nome, e fica `None` quando a busca não acha ninguém com confiança.
    lastfm_url: str | None = None
    spotify_id: str | None = None
    image: str | None = None


class ArtistProfile(BaseModel):
    """Tudo que a página do artista mostra, de três fontes.

    Spotify dá identidade (foto, seguidores, link); Last.fm dá contexto
    (biografia, audiência, tags, parecidos); o acervo em disco diz onde o
    artista aparece nas playlists de quem está logado.
    """

    id: str
    name: str
    image: str | None = None
    spotify_url: str | None = None
    # Sem `followers`/`popularity`: desde a migração de 2026 o objeto do artista
    # do Spotify não traz mais esses campos (nem `genres`). A audiência aqui é a
    # do Last.fm, logo abaixo.

    lastfm_url: str | None = None
    listeners: int | None = None
    playcount: int | None = None
    bio: str | None = None
    tags: list[str] = []

    top_tracks: list[ArtistTrack] = []
    similar: list[SimilarArtist] = []

    # O artista dentro do acervo de quem está logado.
    library_tracks: list[ArtistTrack] = []
    library_track_count: int = 0
    library_playlists: list[PlaylistSummary] = []
    # `False` quando nenhuma playlist foi analisada ainda — a página distingue
    # "não aparece no seu acervo" de "seu acervo ainda não foi varrido".
    library_scanned: bool = False
