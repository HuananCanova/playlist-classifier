"""Fixtures compartilhadas.

Regra desta suíte: nenhum teste toca em Spotify, Last.fm, Deezer ou num modelo
de linguagem. Tudo que sai para a rede é substituído por fixtures. Os testes que
precisam de um modelo de verdade vivem em `backend/evals/` e rodam à parte.
"""
import random

import pytest


@pytest.fixture(autouse=True)
def db_tmp(tmp_path, monkeypatch):
    """Cada teste com um banco novo e os caches em memória vazios.

    Sem isso a suíte gravaria no banco de verdade do app (análises e listagens
    falsas apareceriam na tela) e um teste herdaria o que o anterior guardou.
    """
    from app import cache, db, profile_store

    db.use_path(tmp_path / "app.sqlite3")
    monkeypatch.setattr(profile_store, "STORE_PATH", tmp_path / "profile_legacy")
    profile_store.clear_memo()
    caches = [v for v in vars(cache).values() if isinstance(v, cache.TTLCache)]
    for c in caches:
        c.clear()
    yield db
    for c in caches:
        c.clear()
    profile_store.clear_memo()
    db.use_path(None)


@pytest.fixture(autouse=True)
def spotify_state_tmp(tmp_path, monkeypatch):
    """Bloqueio do Spotify e listagem guardada vão para um diretório descartável.

    Sem isso um teste que simula um 429 longo gravaria um bloqueio de verdade e
    o app real pararia de chamar o Spotify — e o bloqueio real do desenvolvedor
    vazaria para os testes.
    """
    from app import spotify_client

    monkeypatch.setattr(spotify_client, "STATE_PATH", tmp_path / "state")
    monkeypatch.setattr(spotify_client, "_global_until", None)
    monkeypatch.setattr(spotify_client, "_throttled_until", {})
    yield spotify_client

from app.models import PlaylistAnalysis, PlaylistSummary, TrackDetail, TrackGenreInfo

# Três blocos deliberadamente distintos: dá para afirmar o que um agrupamento
# correto deve encontrar, em vez de só checar que ele não explodiu.
BLOCOS = {
    "shoegaze": (
        ["shoegaze", "dream pop", "melancholic", "atmospheric", "guitar", "reverb", "ethereal"],
        ["Slowdive", "Beach House", "My Bloody Valentine", "Cocteau Twins"],
    ),
    "house": (
        ["french house", "electronic", "dance", "disco", "upbeat", "groove", "party"],
        ["Daft Punk", "Justice", "Cassius", "Modjo"],
    ),
    "metal": (
        ["thrash metal", "heavy metal", "aggressive", "fast", "guitar", "riff", "intense"],
        ["Metallica", "Slayer", "Megadeth", "Anthrax"],
    ),
}


def _tracks(por_bloco: int = 12) -> list[TrackGenreInfo]:
    rng = random.Random(7)
    saida = []
    for bloco, (tags, artistas) in BLOCOS.items():
        for i in range(por_bloco):
            escolhidas = rng.sample(tags, k=rng.randint(4, 6))
            saida.append(
                TrackGenreInfo(
                    track_id=f"{bloco}-{i}",
                    name=f"{bloco.title()} Track {i + 1}",
                    artists=[rng.choice(artistas)],
                    album=f"Album {bloco}",
                    duration_ms=rng.randint(150_000, 400_000),
                    popularity=rng.randint(10, 90),
                    genres=escolhidas[:2],
                    subgenre_tags=escolhidas,
                )
            )
    return saida


@pytest.fixture
def analysis() -> PlaylistAnalysis:
    tracks = _tracks()
    return PlaylistAnalysis(
        playlist=PlaylistSummary(id="p1", name="Mistura", track_count=len(tracks)),
        tracks=tracks,
        genre_distribution=[],
        subgenre_distribution=[],
        top_artists=[],
        tracks_missing_genre=0,
        bpm_histogram=[],
    )


# Contraponto ao de cima: dois "blocos" que compartilham quase todo o
# vocabulário. Não existe divisão certa aqui, e o ponto é justamente esse — o
# agrupamento tem que reportar separação fraca em vez de inventar estrutura.
BLOCOS_SOBREPOSTOS = {
    "indie": (
        ["indie rock", "alternative rock", "guitar", "indie", "rock", "melodic"],
        ["The Strokes", "Arctic Monkeys"],
    ),
    "alt": (
        ["alternative rock", "indie rock", "rock", "guitar", "melodic", "indie"],
        ["Interpol", "Editors"],
    ),
}


def _tracks_sobrepostos(por_bloco: int = 12) -> list[TrackGenreInfo]:
    rng = random.Random(11)
    saida = []
    for bloco, (tags, artistas) in BLOCOS_SOBREPOSTOS.items():
        for i in range(por_bloco):
            escolhidas = rng.sample(tags, k=rng.randint(4, 6))
            saida.append(
                TrackGenreInfo(
                    track_id=f"{bloco}-{i}",
                    name=f"{bloco.title()} Track {i + 1}",
                    artists=[rng.choice(artistas)],
                    album=f"Album {bloco}",
                    duration_ms=rng.randint(150_000, 400_000),
                    popularity=rng.randint(10, 90),
                    genres=escolhidas[:2],
                    subgenre_tags=escolhidas,
                )
            )
    return saida


@pytest.fixture
def analysis_sobreposta() -> PlaylistAnalysis:
    tracks = _tracks_sobrepostos()
    return PlaylistAnalysis(
        playlist=PlaylistSummary(id="p3", name="Tudo parecido", track_count=len(tracks)),
        tracks=tracks,
        genre_distribution=[],
        subgenre_distribution=[],
        top_artists=[],
        tracks_missing_genre=0,
        bpm_histogram=[],
    )


@pytest.fixture
def track_detail() -> TrackDetail:
    return TrackDetail(
        track_id="shoegaze-0",
        name="Shoegaze Track 1",
        artists=["Slowdive"],
        album="Album shoegaze",
        duration_ms=280_000,
        tags=["shoegaze", "dream pop", "melancholic"],
        artist_tags=["shoegaze", "dream pop"],
        bpm=96.0,
        preview_url="https://exemplo/preview.mp3",
        match_confidence="alta",
        matched_title="Shoegaze Track 1",
    )


@pytest.fixture
def chroma_tmp(tmp_path, monkeypatch):
    """Aponta o índice vetorial para um diretório descartável.

    Sem isso os testes escreveriam no índice real do desenvolvedor.
    """
    from app import vector_store

    monkeypatch.setattr(vector_store, "CHROMA_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vector_store, "_collection", None)
    yield vector_store
    vector_store._collection = None
