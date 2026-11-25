"""Páginas de subgênero do acervo: contagens e faixas — sem rede."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import subgenre_library, subgenres
from app.models import PlaylistSummary


def _t(tid, lean, unsure=False, blend=None, genres=("psytrance",)):
    return {
        "id": tid, "name": f"Faixa {tid}", "artists": ["A"], "image": None, "bpm": 145.0,
        "genres": list(genres), "subgenre_lean": lean, "subgenre_unsure": unsure,
        "subgenre_blend": blend or [],
    }


def _d(pid, *tracks):
    return {"playlist": {"id": pid, "name": f"Lista {pid}"}, "tracks": list(tracks)}


def _pls(*ids):
    return [PlaylistSummary(id=i, name=f"Lista {i}", track_count=1) for i in ids]


def test_tracks_split_confident_and_leaning():
    digests = {"p1": _d(
        "p1",
        _t("a", "full-on", blend=[["full-on", 0.9], ["goa", 0.1]]),
        _t("b", "full-on", unsure=True, blend=[["full-on", 0.5], ["goa", 0.4]]),
        _t("c", "full-on", blend=[["full-on", 0.7]]),
        _t("d", "goa"),
    )}
    out = subgenre_library.subgenre_tracks(digests, _pls("p1"), "full-on")
    assert [t["id"] for t in out["confident"]] == ["a", "c"]
    assert [t["id"] for t in out["leaning"]] == ["b"]
    assert out["confident"][0]["share"] == 0.9
    assert out["info"]["name"] == "full-on"
    assert out["confident"][0]["playlists"] == [{"id": "p1", "name": "Lista p1"}]


def test_unique_tracks_across_playlists():
    digests = {
        "p1": _d("p1", _t("a", "full-on", blend=[["full-on", 0.6]])),
        "p2": _d("p2", _t("a", "full-on", blend=[["full-on", 0.8]])),
    }
    out = subgenre_library.subgenre_tracks(digests, _pls("p1", "p2"), "Full-On")
    assert len(out["confident"]) == 1
    assert [p["id"] for p in out["confident"][0]["playlists"]] == ["p1", "p2"]
    counts = {s["name"]: s for s in subgenre_library.library_subgenres(digests)}
    assert counts["full-on"]["confident"] == 1


def test_only_account_playlists():
    digests = {"p1": _d("p1", _t("a", "full-on")), "fora": _d("fora", _t("z", "full-on"))}
    out = subgenre_library.subgenre_tracks(digests, _pls("p1"), "full-on")
    assert [t["id"] for t in out["confident"]] == ["a"]


def test_old_digest_without_fields_is_ignored_not_crash():
    velho = {"id": "x", "name": "Velha", "artists": [], "genres": ["psytrance"]}
    digests = {"p1": _d("p1", velho, _t("a", "full-on"))}
    out = subgenre_library.subgenre_tracks(digests, _pls("p1"), "full-on")
    assert [t["id"] for t in out["confident"]] == ["a"]
    assert subgenre_library.library_subgenres({"p1": _d("p1", velho)}) == []


def test_library_lists_full_vocabulary_of_present_genres_with_counts():
    digests = {"p1": _d("p1", _t("a", "full-on"), _t("b", "full-on", unsure=True), _t("c", None))}
    rows = subgenre_library.library_subgenres(digests)
    names = [r["name"] for r in rows]
    assert "full-on" in names and "darkpsy" in names
    full = next(r for r in rows if r["name"] == "full-on")
    assert (full["confident"], full["unsure"]) == (1, 1)
    assert set(full) == {"genre", "name", "bpm", "about", "source", "confident", "unsure"}
    assert full["bpm"] is None or isinstance(full["bpm"], list)
    assert next(r for r in rows if r["name"] == "darkpsy")["confident"] == 0


@pytest.fixture
def rotas(monkeypatch):
    async def listagem(request, refresh=False):
        return _pls("p1")

    async def token(request):
        return "t"

    monkeypatch.setattr(subgenres, "get_valid_access_token", token)
    monkeypatch.setattr(subgenres, "get_playlist_summaries", listagem)
    monkeypatch.setattr(subgenres, "account_key", lambda request: "spotify:eu")
    monkeypatch.setattr(subgenres.profile_store, "load", lambda pid: _d(pid, _t("a", "forest psy")))
    app = FastAPI()
    app.include_router(subgenres.router)
    return TestClient(app)


def test_unknown_subgenre_404(rotas):
    r = rotas.get("/api/subgenres/nao-existe")
    assert r.status_code == 404
    assert "desconhecido" in r.json()["detail"]


def test_routes_list_and_detail_and_enrich_not_swallowed(rotas, monkeypatch):
    assert any(s["name"] == "forest psy" for s in rotas.get("/api/subgenres").json())
    ok = rotas.get("/api/subgenres/forest%20psy")
    assert ok.status_code == 200
    assert [t["id"] for t in ok.json()["confident"]] == ["a"]
    assert rotas.get("/api/subgenres/enrich").json()["running"] is False


def test_divergent_copies_collapse_to_one_record_consistently():
    # p1: puxa para darkpsy (0.4, em dúvida); p2: full-on confiante com 0.8 -> vence p2.
    # Ordem do dict invertida de propósito: o resultado não pode depender dela.
    digests = {
        "p2": _d("p2", _t("a", "full-on", blend=[["full-on", 0.8]])),
        "p1": _d("p1", _t("a", "darkpsy", unsure=True, blend=[["darkpsy", 0.4]])),
    }
    pls = _pls("p1", "p2")
    full = subgenre_library.subgenre_tracks(digests, pls, "full-on")
    dark = subgenre_library.subgenre_tracks(digests, pls, "darkpsy")
    assert [(t["id"], t["share"]) for t in full["confident"]] == [("a", 0.8)]
    assert full["leaning"] == [] and dark["confident"] == [] and dark["leaning"] == []
    assert [p["id"] for p in full["confident"][0]["playlists"]] == ["p1", "p2"]
    rows = {r["name"]: r for r in subgenre_library.library_subgenres(digests)}
    assert (rows["full-on"]["confident"], rows["full-on"]["unsure"]) == (1, 0)
    assert (rows["darkpsy"]["confident"], rows["darkpsy"]["unsure"]) == (0, 0)


def test_collapse_ties_prefer_confident_then_lowest_playlist_id():
    iguais = [["full-on", 0.6]]
    digests = {
        "p1": _d("p1", _t("a", "full-on", unsure=True, blend=iguais)),
        "p2": _d("p2", _t("a", "full-on", blend=iguais)),
    }
    out = subgenre_library.subgenre_tracks(digests, _pls("p1", "p2"), "full-on")
    assert [t["id"] for t in out["confident"]] == ["a"] and out["leaning"] == []
    digests = {
        "p2": _d("p2", _t("a", "full-on", blend=iguais) | {"bpm": 1.0}),
        "p1": _d("p1", _t("a", "full-on", blend=iguais) | {"bpm": 2.0}),
    }
    out = subgenre_library.subgenre_tracks(digests, _pls("p1", "p2"), "full-on")
    assert out["confident"][0]["bpm"] == 2.0
