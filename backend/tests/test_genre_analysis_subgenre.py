"""Análise nova: mistura de subgêneros nas faixas, barras e evidência guardada.

Nada aqui fala com a rede — Spotify, Last.fm e Deezer são substituídos.
"""
import pytest

from app import evidence_store, genre_analysis, lastfm_client
from app.taxonomy import Tag


def _install(monkeypatch, *, artist=None, track=None, deezer=None, tracks=None):
    tracks = tracks or [
        {"id": "t1", "name": "Um", "duration_ms": 1, "album": {}, "artists": [{"name": "A"}]}
    ]

    class FakeSpotify:
        def __init__(self, token):
            pass

        async def get_playlist(self, client, pid):
            return {"id": pid, "name": "P", "snapshot_id": "s1", "images": []}

        async def get_all_playlist_tracks(self, client, pid):
            return tracks

    async def artist_tags(client, name):
        return artist if artist is not None else [Tag("psytrance", 100.0)]

    async def track_tags(client, a, name):
        return track if track is not None else []

    async def deezer_many(client, pairs):
        info = deezer or {"deezer_id": None, "bpm": None}
        return [{"preview_url": None, "deezer_url": None, **info} for _ in pairs]

    monkeypatch.setattr(genre_analysis, "SpotifyClient", FakeSpotify)
    monkeypatch.setattr(genre_analysis, "get_artist_tags", artist_tags)
    monkeypatch.setattr(genre_analysis, "get_track_tags", track_tags)
    monkeypatch.setattr(genre_analysis, "get_deezer_many", deezer_many)


async def test_build_stores_separated_tags_and_blend(monkeypatch):
    _install(
        monkeypatch,
        track=[Tag("full-on", 80.0)],
        deezer={"deezer_id": 7, "bpm": 146.0},
    )

    analysis = await genre_analysis.build_playlist_analysis("tok", "p1")

    track = analysis.tracks[0]
    assert track.subgenre == "full-on"
    assert track.subgenre_lean == "full-on"
    assert analysis.subgenre_bars[0].label == "full-on"
    assert analysis.subgenre_bars[0].confident > 0
    assert [(g.label, g.count) for g in analysis.subgenre_distribution] == [("full-on", 1)]

    ev = evidence_store.get_many(["t1"])["t1"]
    assert ev.artist_tags == [Tag("psytrance", 100.0)]
    assert ev.track_tags == [Tag("full-on", 80.0)]
    assert (ev.bpm, ev.deezer_id) == (146.0, 7)
    assert ev.deezer_checked_at is not None


async def test_unsure_track_counts_in_bars_unsure_part(monkeypatch):
    # Só o artista falou (aponta um subgênero): sem tag de faixa nem BPM, o resultado é incerto.
    _install(monkeypatch, artist=[Tag("full-on", 100.0)], track=[])

    analysis = await genre_analysis.build_playlist_analysis("tok", "p1")

    track = analysis.tracks[0]
    assert track.subgenre is None
    assert track.subgenre_unsure
    assert track.subgenre_blend, "uma faixa incerta ainda tem mistura"
    assert all(b.confident == 0 and b.unsure > 0 for b in analysis.subgenre_bars)


async def test_failed_lastfm_lookup_is_not_stored_as_empty(monkeypatch):
    _install(monkeypatch)

    async def failing_track_tags(client, a, name):
        return lastfm_client.NoAnswer()

    monkeypatch.setattr(genre_analysis, "get_track_tags", failing_track_tags)

    await genre_analysis.build_playlist_analysis("tok", "p1")

    ev = evidence_store.get_many(["t1"])["t1"]
    assert ev.artist_tags == [Tag("psytrance", 100.0)]
    assert ev.track_tags is None


async def test_without_audio_leaves_deezer_fields_alone(monkeypatch):
    _install(monkeypatch)

    await genre_analysis.build_playlist_analysis("tok", "p1", include_audio=False)

    ev = evidence_store.get_many(["t1"])["t1"]
    assert ev.deezer_checked_at is None and ev.bpm is None


async def test_uses_stored_bpm_when_deezer_is_unknown(monkeypatch):
    _install(monkeypatch)
    evidence_store.put(evidence_store.TrackEvidence("t1", bpm=160.0))

    analysis = await genre_analysis.build_playlist_analysis("tok", "p1", include_audio=False)

    assert analysis.tracks[0].subgenre_lean == "forest psy"
    assert evidence_store.get_many(["t1"])["t1"].bpm == 160.0


async def test_track_detail_has_blend_and_stores_evidence(monkeypatch):
    from app import enrichment_store, tracks

    async def fake_parallel(client, artist, title, duration):
        return {"bpm": 146.0, "preview_url": None, "deezer_url": None}, [Tag("full-on", 80.0)], [Tag("psytrance", 100.0)]

    monkeypatch.setattr(tracks, "_buscar_em_paralelo", fake_parallel)
    enrichment_store.put_spotify_tracks(
        [{"id": "t9", "name": "Nove", "duration_ms": 1, "album": {}, "artists": [{"name": "A"}]}]
    )

    detail = await tracks.build_track_detail("tok", "t9")

    assert detail.subgenre == "full-on" and detail.subgenre_lean == "full-on"
    assert detail.subgenre_blend and detail.subgenre_evidence
    ev = evidence_store.get_many(["t9"])["t9"]
    assert ev.track_tags == [Tag("full-on", 80.0)] and ev.bpm == 146.0


async def test_track_detail_reference_follows_lean(monkeypatch):
    from app import enrichment_store, tracks
    from app.cache import track_detail_cache

    async def fake_parallel(client, artist, title, duration):
        return {"bpm": 146.0, "preview_url": None, "deezer_url": None}, [Tag("full-on", 80.0)], [Tag("psytrance", 100.0)]

    monkeypatch.setattr(tracks, "_buscar_em_paralelo", fake_parallel)
    enrichment_store.put_spotify_tracks(
        [{"id": "t10", "name": "Dez", "duration_ms": 1, "album": {}, "artists": [{"name": "A"}]}]
    )
    track_detail_cache.pop("t10", None)
    ref = (await tracks.build_track_detail("tok", "t10")).subgenre_reference
    assert ref["name"] == "full-on" and len(ref["bpm"]) == 2 and "source" in ref and "about" in ref

    assert tracks._referencia(None) is None
    assert tracks._referencia("não existe") is None
