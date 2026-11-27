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
        deezer = {"deezer_id": 3, "bpm": 146.0, "preview_url": None, "deezer_url": None, "confianca": "alta"}
        return deezer, [Tag("full-on", 80.0)], [Tag("psytrance", 100.0)]

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
        deezer = {"deezer_id": 3, "bpm": 146.0, "preview_url": None, "deezer_url": None, "confianca": "alta"}
        return deezer, [Tag("full-on", 80.0)], [Tag("psytrance", 100.0)]

    monkeypatch.setattr(tracks, "_buscar_em_paralelo", fake_parallel)
    enrichment_store.put_spotify_tracks(
        [{"id": "t10", "name": "Dez", "duration_ms": 1, "album": {}, "artists": [{"name": "A"}]}]
    )
    track_detail_cache.pop("t10", None)
    ref = (await tracks.build_track_detail("tok", "t10")).subgenre_reference
    assert ref["name"] == "full-on" and len(ref["bpm"]) == 2 and "source" in ref and "about" in ref

    assert tracks._referencia(None) is None
    assert tracks._referencia("não existe") is None


# ── colaboração: as tags dos artistas se juntam com o maior peso ─────────────


async def test_collab_artist_tags_keep_max_weight_not_sum(monkeypatch):
    tracks = [{"id": "t1", "name": "Um", "duration_ms": 1, "album": {}, "artists": [{"name": "A"}, {"name": "B"}]}]
    _install(monkeypatch, tracks=tracks)

    async def artist_tags(client, name):
        return {
            "A": [Tag("psytrance", 100.0), Tag("full-on", 40.0)],
            "B": [Tag("psytrance", 90.0), Tag("Full-On", 70.0)],
        }[name]

    monkeypatch.setattr(genre_analysis, "get_artist_tags", artist_tags)

    await genre_analysis.build_playlist_analysis("tok", "p1", include_audio=False)

    ev = evidence_store.get_many(["t1"])["t1"]
    # A mesma regra do job de enriquecimento: uma tag por nome, com o maior peso.
    assert ev.artist_tags == [Tag("psytrance", 100.0), Tag("Full-On", 70.0)]


def test_merge_tags_is_the_job_rule():
    from app import taxonomy

    merged = taxonomy.merge_tags([Tag("a", 10.0), Tag("B", 50.0)], [Tag(" b ", 80.0), Tag("c", 10.0)])
    assert merged == [Tag(" b ", 80.0), Tag("a", 10.0), Tag("c", 10.0)]


# ── completar com áudio uma análise feita sem ──────────────────────────────


async def _sem_audio_depois_com(monkeypatch, resposta):
    _install(monkeypatch)  # artista só "psytrance": sem voto de subgênero
    analysis = await genre_analysis.build_playlist_analysis("tok", "p1", include_audio=False)
    assert analysis.tracks[0].subgenre_blend == []

    async def deezer_many(client, pairs):
        return [resposta for _ in pairs]

    monkeypatch.setattr(genre_analysis, "get_deezer_many", deezer_many)
    return await genre_analysis.add_audio(analysis)


async def test_add_audio_recomputes_blend_and_bars(monkeypatch):
    completed = await _sem_audio_depois_com(
        monkeypatch, {"deezer_id": 9, "bpm": 100.0, "preview_url": None, "deezer_url": "u"}
    )

    track = completed.tracks[0]
    assert track.bpm == 100.0
    assert track.subgenre_lean == "psychill"
    assert track.subgenre == "psychill"
    assert any(e.source == "tempo" for e in track.subgenre_evidence)
    assert [(b.label, b.confident > 0) for b in completed.subgenre_bars] == [("psychill", True)]
    assert [(g.label, g.count) for g in completed.subgenre_distribution] == [("psychill", 1)]

    ev = evidence_store.get_many(["t1"])["t1"]
    assert (ev.bpm, ev.deezer_id) == (100.0, 9) and ev.deezer_checked_at is not None


async def test_add_audio_records_not_found(monkeypatch):
    from app.deezer_client import NotFound

    await _sem_audio_depois_com(
        monkeypatch, NotFound({"deezer_id": None, "bpm": None, "preview_url": None, "deezer_url": None})
    )
    ev = evidence_store.get_many(["t1"])["t1"]
    assert ev.deezer_checked_at is not None and ev.bpm is None and ev.deezer_id is None


async def test_add_audio_failure_stores_nothing(monkeypatch):
    await _sem_audio_depois_com(monkeypatch, {"deezer_id": None, "bpm": None, "preview_url": None, "deezer_url": None})
    ev = evidence_store.get_many(["t1"])["t1"]
    assert ev.deezer_checked_at is None and ev.bpm is None


# ── página da faixa: correspondência aproximada do Deezer não vira evidência ─


async def _detalhe_com_deezer(monkeypatch, track_id, deezer):
    from app import enrichment_store, tracks
    from app.cache import track_detail_cache

    async def fake_parallel(client, artist, title, duration):
        return deezer, [Tag("full-on", 80.0)], [Tag("psytrance", 100.0)]

    monkeypatch.setattr(tracks, "_buscar_em_paralelo", fake_parallel)
    enrichment_store.put_spotify_tracks(
        [{"id": track_id, "name": "X", "duration_ms": 1, "album": {}, "artists": [{"name": "A"}]}]
    )
    track_detail_cache.pop(track_id, None)
    await tracks.build_track_detail("tok", track_id)
    return evidence_store.get_many([track_id])[track_id]


async def test_track_detail_approximate_deezer_match_is_not_stored(monkeypatch):
    deezer = {"deezer_id": 5, "bpm": 146.0, "preview_url": None, "deezer_url": None, "confianca": "aproximada"}
    ev = await _detalhe_com_deezer(monkeypatch, "t20", deezer)
    assert (ev.bpm, ev.deezer_id, ev.deezer_checked_at) == (None, None, None)
    assert ev.track_tags == [Tag("full-on", 80.0)]


async def test_track_detail_high_confidence_match_stores_id(monkeypatch):
    deezer = {"deezer_id": 5, "bpm": 146.0, "preview_url": None, "deezer_url": None, "confianca": "alta"}
    ev = await _detalhe_com_deezer(monkeypatch, "t21", deezer)
    assert (ev.bpm, ev.deezer_id) == (146.0, 5) and ev.deezer_checked_at is not None


async def test_buscar_faixa_returns_deezer_id():
    import httpx

    from app import deezer_client

    def handler(req):
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"data": [{"id": 77, "title": "Raro", "artist": {"name": "Zeta"}, "link": "l"}]})
        return httpx.Response(200, json={"id": 77, "bpm": 145})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        info = await deezer_client.buscar_faixa(client, "Zeta", "Raro")
    assert info["deezer_id"] == 77 and info["confianca"] == "alta"


# ── IA: subgêneros com a parte afirmada separada da incerta ────────────────


async def test_ai_tool_separates_confident_from_unsure(monkeypatch):
    import json

    from app import ai_tools

    tracks = [
        {"id": f"t{i}", "name": f"F{i}", "duration_ms": 1, "album": {}, "artists": [{"name": "A"}]} for i in range(3)
    ]
    _install(monkeypatch, tracks=tracks)

    async def track_tags(client, a, name):
        # F0 tem tag de faixa (afirmada); F1 e F2 só têm o artista (incertas).
        return [Tag("full-on", 100.0)] if name == "F0" else []

    async def artist_tags(client, name):
        return [Tag("psytrance", 100.0), Tag("full-on", 50.0)]

    monkeypatch.setattr(genre_analysis, "get_track_tags", track_tags)
    monkeypatch.setattr(genre_analysis, "get_artist_tags", artist_tags)
    monkeypatch.setattr(ai_tools, "build_playlist_analysis", genre_analysis.build_playlist_analysis)

    payload = json.loads(await ai_tools.analisar_playlist_json("tok", "p-ia"))
    assert payload["subgeneros"] == [{"subgenero": "full-on", "faixas_confiantes": 1, "faixas_incertas": 2}]


# ── selo: a análise nova usa o guardado, sem pedir à rede ──────────────────


def _sem_rede_de_selo(monkeypatch):
    from app import deezer_client

    async def proibido(*args, **kwargs):
        raise AssertionError("análise nova não pede selo à rede")

    monkeypatch.setattr(deezer_client, "get_label_for_track", proibido)
    monkeypatch.setattr(deezer_client, "get_track_label", proibido)
    monkeypatch.setattr(deezer_client, "_album_label", proibido)


async def test_new_analysis_uses_stored_label_without_network(monkeypatch):
    _install(monkeypatch, track=[Tag("forest psy", 80.0)])
    _sem_rede_de_selo(monkeypatch)
    evidence_store.put(evidence_store.TrackEvidence("t1", deezer_id=7, label="Parvati Records", label_checked_at=1.0))

    analysis = await genre_analysis.build_playlist_analysis("tok", "p1")

    track = analysis.tracks[0]
    assert track.subgenre == "forest psy"
    assert any(e.source == "label" for e in track.subgenre_evidence)
    # Guardar a evidência nova não apaga o selo.
    assert evidence_store.get_many(["t1"])["t1"].label == "Parvati Records"


async def test_new_analysis_label_alone_is_unsure_lean(monkeypatch):
    _install(monkeypatch)  # artista só "psytrance"
    _sem_rede_de_selo(monkeypatch)
    evidence_store.put(evidence_store.TrackEvidence("t1", label="Suntrip Records", label_checked_at=1.0))

    analysis = await genre_analysis.build_playlist_analysis("tok", "p1", include_audio=False)

    track = analysis.tracks[0]
    assert track.subgenre_lean == "goa trance" and track.subgenre_unsure is True


async def test_add_audio_keeps_stored_label(monkeypatch):
    _install(monkeypatch)  # artista só "psytrance": sem voto de subgênero
    _sem_rede_de_selo(monkeypatch)
    analysis = await genre_analysis.build_playlist_analysis("tok", "p1", include_audio=False)
    assert analysis.tracks[0].subgenre_blend == []
    # O job de enriquecimento guardou o selo enquanto isso.
    evidence_store.put(evidence_store.TrackEvidence("t1", label="Suntrip Records", label_checked_at=1.0))

    async def deezer_many(client, pairs):
        return [{"deezer_id": 9, "bpm": None, "preview_url": None, "deezer_url": "u"} for _ in pairs]

    monkeypatch.setattr(genre_analysis, "get_deezer_many", deezer_many)
    completed = await genre_analysis.add_audio(analysis)
    assert completed.tracks[0].subgenre_lean == "goa trance"
    assert any(e.source == "label" for e in completed.tracks[0].subgenre_evidence)


# ── página da faixa: o selo ─────────────────────────────────────────────────


async def _detalhe_com_selo(monkeypatch, track_id, deezer, selo_da_rede, chamadas):
    from app import enrichment_store, tracks
    from app.cache import track_detail_cache

    async def fake_parallel(client, artist, title, duration):
        return deezer, [Tag("forest psy", 80.0)], [Tag("psytrance", 100.0)]

    async def fake_label(client, deezer_id):
        chamadas.append(deezer_id)
        return selo_da_rede

    monkeypatch.setattr(tracks, "_buscar_em_paralelo", fake_parallel)
    monkeypatch.setattr(tracks, "get_label_for_track", fake_label)
    enrichment_store.put_spotify_tracks(
        [{"id": track_id, "name": "X", "duration_ms": 1, "album": {}, "artists": [{"name": "A"}]}]
    )
    track_detail_cache.pop(track_id, None)
    return await tracks.build_track_detail("tok", track_id)


async def test_track_detail_fetches_missing_label_once_and_exposes_info(monkeypatch):
    evidence_store.put(evidence_store.TrackEvidence("t30", deezer_id=11, deezer_checked_at=1.0))
    chamadas: list = []

    detail = await _detalhe_com_selo(monkeypatch, "t30", None, "Parvati Records", chamadas)

    assert chamadas == [11]
    assert detail.label == "Parvati Records"
    assert detail.label_info.name == "Parvati Records"
    assert detail.label_info.nota and detail.label_info.fonte.startswith("http")
    assert [(s.label, s.share) for s in detail.label_info.shares] == [("forest psy", 1.0)]
    assert any(e.source == "label" for e in detail.subgenre_evidence)
    ev = evidence_store.get_many(["t30"])["t30"]
    assert ev.label == "Parvati Records" and ev.label_checked_at is not None

    # Segunda visita (sem cache em memória): o selo já está guardado.
    await _detalhe_com_selo(monkeypatch, "t30", None, "Parvati Records", chamadas)
    assert chamadas == [11]


async def test_track_detail_uses_fresh_deezer_id_for_label(monkeypatch):
    deezer = {"deezer_id": 42, "bpm": None, "preview_url": None, "deezer_url": None, "confianca": "alta"}
    chamadas: list = []
    detail = await _detalhe_com_selo(monkeypatch, "t31", deezer, "Kontor Records", chamadas)

    assert chamadas == [42]
    assert detail.label == "Kontor Records" and detail.label_info is None
    assert evidence_store.get_many(["t31"])["t31"].label == "Kontor Records"


async def test_track_detail_label_failure_stores_nothing(monkeypatch):
    evidence_store.put(evidence_store.TrackEvidence("t32", deezer_id=12, deezer_checked_at=1.0))
    chamadas: list = []
    detail = await _detalhe_com_selo(monkeypatch, "t32", None, None, chamadas)

    assert chamadas == [12] and detail.label is None and detail.label_info is None
    ev = evidence_store.get_many(["t32"])["t32"]
    assert ev.label is None and ev.label_checked_at is None


async def test_track_detail_without_deezer_match_does_not_ask_label(monkeypatch):
    deezer = {"deezer_id": 5, "bpm": None, "preview_url": None, "deezer_url": None, "confianca": "aproximada"}
    chamadas: list = []
    await _detalhe_com_selo(monkeypatch, "t33", deezer, "Parvati Records", chamadas)
    assert chamadas == []
