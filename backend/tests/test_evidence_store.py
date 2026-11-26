"""Evidência por faixa: o que o banco guarda para reclassificar sem rede."""
from app import evidence_store
from app.evidence_store import TrackEvidence
from app.models import EvidenceLine, SubgenreShare, TrackGenreInfo
from app.subgenre import Evidence, SubgenreResult, subgenre_fields
from app.taxonomy import Tag


def test_put_and_get_roundtrip():
    evidence_store.put(
        TrackEvidence("t1", artist_tags=[Tag("psytrance", 80)], track_tags=[Tag("goa", 55)],
                      bpm=145.0, deezer_id=7, deezer_checked_at=123.0)
    )
    got = evidence_store.get_many(["t1", "nada"])
    assert set(got) == {"t1"}
    ev = got["t1"]
    assert ev.artist_tags == [Tag("psytrance", 80)]
    assert ev.track_tags == [Tag("goa", 55)]
    assert (ev.bpm, ev.deezer_id, ev.deezer_checked_at) == (145.0, 7, 123.0)


def test_put_does_not_erase_known_values():
    evidence_store.put(TrackEvidence("t1", artist_tags=[Tag("psytrance", 80)], bpm=145.0, deezer_id=7,
                                     deezer_checked_at=1.0))
    evidence_store.put(TrackEvidence("t1", track_tags=[]))
    ev = evidence_store.get_many(["t1"])["t1"]
    assert ev.artist_tags == [Tag("psytrance", 80)]
    assert ev.track_tags == []  # lista vazia é resposta de verdade, não ausência
    assert (ev.bpm, ev.deezer_id, ev.deezer_checked_at) == (145.0, 7, 1.0)


def test_missing_lists_incomplete_rows():
    full = dict(artist_tags=[], track_tags=[], deezer_checked_at=1.0)
    evidence_store.put(TrackEvidence("completa", **full))
    # Deezer respondeu "não achei": bpm e id vazios, mas é resposta.
    evidence_store.put(TrackEvidence("sem_deezer_match", **full))
    evidence_store.put(TrackEvidence("sem_artista", track_tags=[], deezer_checked_at=1.0))
    evidence_store.put(TrackEvidence("sem_faixa", artist_tags=[], deezer_checked_at=1.0))
    evidence_store.put(TrackEvidence("sem_deezer", artist_tags=[], track_tags=[]))
    ids = ["completa", "sem_deezer_match", "sem_artista", "sem_faixa", "sem_deezer", "nova"]
    assert evidence_store.missing(ids) == ["sem_artista", "sem_faixa", "sem_deezer", "nova"]
    assert evidence_store.missing([]) == []


def test_subgenre_fields_maps_result():
    result = SubgenreResult(
        blend=[("goa", 0.61234), ("full-on", 0.38766)], lean="goa", subgenre="goa", confidence=0.6,
        unsure=False, evidence=[Evidence("track_tags", "goa", "goa (55)"), Evidence("tempo", None, "145 BPM")],
    )
    fields = subgenre_fields(result)
    assert set(fields) == {"subgenre_blend", "subgenre_lean", "subgenre_confidence", "subgenre_unsure",
                           "subgenre_evidence"}
    assert fields["subgenre_blend"] == [SubgenreShare(label="goa", share=0.612), SubgenreShare(label="full-on", share=0.388)]
    assert fields["subgenre_evidence"][1] == EvidenceLine(source="tempo", says=None, detail="145 BPM")
    empty = subgenre_fields(SubgenreResult([], None, None, 0.0, False, []))
    assert empty["subgenre_confidence"] is None
    # Serve de kwargs do modelo.
    info = TrackGenreInfo(track_id="t", name="n", artists=[], duration_ms=1, genres=[], subgenre_tags=[], **fields)
    assert info.subgenre_blend[0].label == "goa"
