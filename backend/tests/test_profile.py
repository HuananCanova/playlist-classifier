"""Perfil: agregação, resumos em disco e a varredura enxuta.

Nada aqui fala com a rede — Spotify, Last.fm e Deezer são substituídos.
"""
import asyncio
from collections import Counter

import pytest

from app import genre_analysis, indexer, profile_store
from app.cache import playlist_analysis_cache
from app.models import PlaylistAnalysis, PlaylistSummary, TrackGenreInfo
from app.profile_stats import build_profile_stats, effective_count


def _t(tid, artists, genres=(), tags=(), added="2024-01-10T00:00:00Z", year=2001, **extra):
    return {
        "id": tid,
        "name": f"Faixa {tid}",
        "artists": list(artists),
        "duration_ms": 200_000,
        "popularity": extra.get("popularity", 50),
        "explicit": extra.get("explicit", False),
        "bpm": extra.get("bpm"),
        "added_at": added,
        "release_year": year,
        "genres": list(genres),
        "tags": list(tags),
    }


def _pl(pid, name, n=0, snapshot="s1"):
    return {"id": pid, "name": name, "image": None, "track_count": n, "snapshot_id": snapshot}


@pytest.fixture
def store_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_store, "STORE_PATH", tmp_path / "profile")
    profile_store.clear_memo()
    yield profile_store
    profile_store.clear_memo()


# ── agregação ────────────────────────────────────────────────────────────────

def test_sem_resumo_nao_ha_estatistica():
    assert build_profile_stats([_pl("a", "A", 3)], {}) is None


def test_faixa_repetida_conta_uma_vez_no_acervo_e_duas_na_linha_do_gosto():
    """Repetir uma faixa não infla o artista, mas conta como escolher de novo."""
    digests = {
        "a": {"tracks": [_t("x", ["Slowdive"], ["shoegaze"]), _t("y", ["Slowdive"], ["shoegaze"])]},
        "b": {"tracks": [_t("x", ["Slowdive"], ["shoegaze"], added="2024-03-02T00:00:00Z")]},
    }
    stats = build_profile_stats([_pl("a", "A", 2), _pl("b", "B", 1)], digests)

    assert stats["library"]["unique_tracks"] == 2
    assert stats["top_artists"] == [{"name": "Slowdive", "tracks": 2, "playlists": 2}]
    assert stats["top_genres"] == [{"label": "shoegaze", "count": 2}]
    # As três adições são de 2024, inclusive a repetida.
    assert stats["taste_timeline"]["years"] == [{"year": 2024, "tracks": 3, "counts": [3.0, 0.0]}]


def test_o_perfil_nao_fala_de_explicito_nem_de_repeticao():
    """O painel é um retrato do gosto: estes números não descrevem gosto."""
    digests = {"a": {"tracks": [_t("x", ["A"], ["rock"], explicit=True), _t("x", ["A"], ["rock"])]}}
    stats = build_profile_stats([_pl("a", "A", 2)], digests)

    assert "explicit_share" not in stats["library"]
    assert "repeated_entries" not in stats["library"]
    assert "repeated_tracks" not in stats
    assert "added_timeline" not in stats


def test_linha_do_gosto_reparte_a_faixa_entre_os_generos_e_preenche_anos_vazios():
    digests = {
        "a": {
            "tracks": [
                _t("1", ["A"], ["rock", "shoegaze"], added="2021-05-01T00:00:00Z"),
                _t("2", ["B"], ["raro"], added="2023-02-01T00:00:00Z"),
                _t("3", ["C"], [], added="2023-02-01T00:00:00Z"),
                _t("4", ["D"], ["rock"], added="1970-01-01T00:00:00Z"),
            ]
        }
    }
    stats = build_profile_stats([_pl("a", "A", 4)], digests)
    timeline = stats["taste_timeline"]

    # Dois gêneros empatados: a ordem vem da contagem, com desempate estável.
    assert set(timeline["genres"]) == {"rock", "shoegaze", "raro"}
    rock = timeline["genres"].index("rock")
    anos = {y["year"]: y for y in timeline["years"]}
    # A faixa com dois gêneros vale meia em cada.
    assert anos[2021]["counts"][rock] == 0.5
    assert anos[2021]["tracks"] == 1
    # 2022 não teve adição, mas continua no eixo.
    assert anos[2022]["tracks"] == 0
    # A faixa sem gênero nenhum não entra; a de gênero raro é do topo aqui.
    assert anos[2023]["tracks"] == 1
    # Data desconhecida (1970) não vira ano.
    assert 1970 not in anos


def test_faixas_e_andamentos_caem_nas_suas_faixas_de_escala():
    digests = {
        "a": {
            "tracks": [
                _t("1", ["A"], popularity=5, bpm=80.0),
                _t("2", ["B"], popularity=95, bpm=128.0),
                _t("3", ["C"], popularity=None, bpm=None),
            ]
        }
    }
    stats = build_profile_stats([_pl("a", "A", 3)], digests)

    assert [b["count"] for b in stats["popularity_bands"]] == [1, 0, 0, 0, 1]
    assert [z["count"] for z in stats["tempo_zones"]] == [1, 0, 1, 0, 0]
    # Só a faixa realmente obscura vira garimpo.
    assert [c["id"] for c in stats["deep_cuts"]] == ["1"]


def test_sem_popularidade_nem_bpm_as_escalas_somem_em_vez_de_mentir_zero():
    digests = {"a": {"tracks": [_t("1", ["A"], popularity=None, bpm=None)]}}
    stats = build_profile_stats([_pl("a", "A", 1)], digests)

    assert stats["popularity_bands"] == []
    assert stats["tempo_zones"] == []
    assert stats["deep_cuts"] == []
    assert stats["library"]["avg_popularity"] is None


def test_decadas_tags_finas_e_medias_opcionais():
    digests = {
        "a": {
            "tracks": [
                _t("1", ["A"], ["rock"], ["rock", "post-punk"], year=1979, bpm=120.0),
                _t("2", ["B"], ["rock"], ["Post-Punk"], year=1985, popularity=None, explicit=None),
                _t("3", ["C"], [], [], year=None),
            ]
        }
    }
    stats = build_profile_stats([_pl("a", "A", 3)], digests)

    assert stats["decades"] == [{"decade": 1970, "count": 1}, {"decade": 1980, "count": 1}]
    # "rock" é gênero amplo, então não se repete como tag fina;
    # a caixa diferente de "Post-Punk" não divide a contagem.
    assert stats["top_tags"] == [{"label": "post-punk", "count": 2}]
    lib = stats["library"]
    assert lib["avg_bpm"] == 120.0 and lib["bpm_known"] == 1
    assert lib["popularity_known"] == 2
    assert lib["tracks_with_genre"] == 2
    assert lib["oldest_track"]["year"] == 1979


def test_tag_fina_que_e_genero_de_outro_artista_nao_se_repete():
    digests = {
        "a": {
            "tracks": [
                _t("1", ["A"], ["indie"], ["dream pop"]),
                # "Indie" não é gênero do artista B, mas é do A: já está no quadro de gêneros.
                _t("2", ["B"], ["folk"], ["Indie", "dream pop"]),
            ]
        }
    }
    stats = build_profile_stats([_pl("a", "A", 2)], digests)

    assert stats["top_tags"] == [{"label": "dream pop", "count": 2}]


def test_diversidade_efetiva():
    assert effective_count(Counter({"a": 10})) == pytest.approx(1.0)
    assert effective_count(Counter({"a": 5, "b": 5})) == pytest.approx(2.0)
    # Um gênero dominante com aparições soltas fica perto de 1, não de 4.
    assert effective_count(Counter({"a": 97, "b": 1, "c": 1, "d": 1})) < 1.3


# ── resumos em disco ─────────────────────────────────────────────────────────

def _analysis(snapshot="s1", bpm=None):
    return PlaylistAnalysis(
        playlist=PlaylistSummary(id="p1", name="Mistura", track_count=1, snapshot_id=snapshot),
        tracks=[
            TrackGenreInfo(
                track_id="t1", name="Um", artists=["A"], duration_ms=1000,
                genres=["rock"], subgenre_tags=["rock"], bpm=bpm,
            )
        ],
        genre_distribution=[], subgenre_distribution=[], top_artists=[],
        bpm_histogram=[], tracks_missing_genre=0,
    )


def test_resumo_sobrevive_ao_reinicio(store_tmp):
    store_tmp.save(_analysis(), has_audio=True)
    store_tmp.clear_memo()  # simula outro processo
    digest = store_tmp.load("p1")
    assert digest["snapshot_id"] == "s1"
    assert digest["tracks"][0]["genres"] == ["rock"]


def test_resumo_sem_audio_nao_apaga_o_bpm_da_mesma_versao(store_tmp):
    store_tmp.save(_analysis(bpm=128.0), has_audio=True)
    store_tmp.save(_analysis(bpm=None), has_audio=False)
    assert store_tmp.load("p1")["tracks"][0]["bpm"] == 128.0

    # Mas uma versão nova da playlist substitui, com ou sem áudio.
    store_tmp.save(_analysis(snapshot="s2"), has_audio=False)
    assert store_tmp.load("p1")["snapshot_id"] == "s2"


def test_frescor_pelo_snapshot():
    assert not profile_store.is_fresh(None, "s1")
    assert profile_store.is_fresh({"snapshot_id": "s1"}, "s1")
    assert not profile_store.is_fresh({"snapshot_id": "s1"}, "s2")
    assert profile_store.is_fresh({"snapshot_id": None}, "s2")


def test_pendentes_ignoram_vazias_e_frescas_e_vem_menores_primeiro(store_tmp):
    """A fila da varredura única: falta resumo OU falta índice."""
    store_tmp.save(_analysis(snapshot="s1"), has_audio=False)  # p1 tem resumo
    playlists = [
        {"id": "p1", "name": "pronta", "track_count": 1, "snapshot_id": "s1"},
        {"id": "big", "name": "grande", "track_count": 900, "snapshot_id": "x"},
        {"id": "empty", "name": "vazia", "track_count": 0, "snapshot_id": "x"},
        {"id": "small", "name": "pequena", "track_count": 12, "snapshot_id": "x"},
    ]
    estado = {"p1": "s1", "big": "x"}  # "big" já está no índice, mas sem resumo
    assert [p["id"] for p in indexer.pendentes_da_conta(playlists, estado)] == ["small", "big"]


def test_estimativa_de_chamadas():
    # 1 de metadados + 1 por página de 100 faixas.
    assert indexer.estimar_chamadas([{"track_count": 12}, {"track_count": 250}]) == 2 + 4


# ── análise enxuta ───────────────────────────────────────────────────────────

@pytest.fixture
def fake_sources(monkeypatch, store_tmp):
    calls = Counter()

    class FakeSpotify:
        def __init__(self, token):
            pass

        async def get_playlist(self, client, pid):
            calls["spotify"] += 1
            await asyncio.sleep(0.01)
            return {"id": pid, "name": "P", "snapshot_id": "s9", "images": []}

        async def get_all_playlist_tracks(self, client, pid):
            return [
                {
                    "id": "t1", "name": "Um", "duration_ms": 1, "explicit": True,
                    "added_at": "2024-05-01T00:00:00Z",
                    "album": {"name": "Al", "release_date": "1997-05-21", "images": []},
                    "artists": [{"name": "A"}],
                }
            ]

    async def artist_tags(client, name):
        return ["rock"]

    async def track_tags(client, artist, name):
        return ["britpop"]

    async def deezer_many(client, pairs):
        calls["deezer"] += 1
        return [{"bpm": 100.0, "preview_url": None, "deezer_url": None} for _ in pairs]

    monkeypatch.setattr(genre_analysis, "SpotifyClient", FakeSpotify)
    monkeypatch.setattr(genre_analysis, "get_artist_tags", artist_tags)
    monkeypatch.setattr(genre_analysis, "get_track_tags", track_tags)
    monkeypatch.setattr(genre_analysis, "get_deezer_many", deezer_many)
    playlist_analysis_cache.clear()
    yield calls
    playlist_analysis_cache.clear()


async def test_sem_audio_pula_o_deezer_e_nao_ocupa_o_cache_da_pagina(fake_sources, store_tmp):
    analysis = await genre_analysis.build_playlist_analysis("tok", "p9", include_audio=False)

    assert fake_sources["deezer"] == 0
    assert analysis.tracks[0].bpm is None
    assert analysis.tracks[0].release_year == 1997
    assert analysis.tracks[0].added_at == "2024-05-01T00:00:00Z"
    assert "p9" not in playlist_analysis_cache
    # E ainda assim deixa o resumo para o perfil.
    assert store_tmp.load("p9")["snapshot_id"] == "s9"


async def test_subgeneros_nao_repetem_os_generos(fake_sources, store_tmp):
    analysis = await genre_analysis.build_playlist_analysis("tok", "p9", include_audio=False)

    assert [g.label for g in analysis.genre_distribution] == ["rock"]
    assert [g.label for g in analysis.subgenre_distribution] == ["britpop"]
    # A faixa continua com todas as tags: agrupamento e busca usam as duas.
    assert analysis.tracks[0].subgenre_tags == ["britpop", "rock"]


async def test_pedidos_simultaneos_da_mesma_playlist_viram_uma_analise(fake_sources):
    results = await asyncio.gather(
        genre_analysis.build_playlist_analysis("tok", "p9"),
        genre_analysis.build_playlist_analysis("tok", "p9"),
        # Quem não precisa de áudio aproveita a análise completa em voo.
        genre_analysis.build_playlist_analysis("tok", "p9", include_audio=False),
    )
    assert fake_sources["spotify"] == 1
    assert fake_sources["deezer"] == 1
    assert all(r.tracks[0].bpm == 100.0 for r in results)
