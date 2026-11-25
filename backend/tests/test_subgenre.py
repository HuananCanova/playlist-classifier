"""Modelo de evidência de subgênero: funções puras, sem rede nem banco."""
from app import subgenre
from app.subgenre import EMPTY_RESULT, SourceResult, blend, tags_source, tempo_source
from app.taxonomy import Tag


def _shares(result):
    return dict(result.blend)


def test_tempo_inside_range_votes_that_subgenre():
    # 146 cai dentro de várias faixas sobrepostas; full-on empata no topo.
    source = tempo_source("psytrance", 146)
    top = max(source.distribution.values())
    assert source.distribution["full-on"] == top
    assert source.distribution.get("progressive psytrance", 0) == 0
    assert source.distribution.get("psy-techno", 0) == 0
    assert abs(sum(source.distribution.values()) - 1) < 1e-9
    # Com o empate, a evidência cita o primeiro por nome (darkpsy), não full-on.
    assert source.evidence[0].says == "darkpsy"
    assert source.evidence[0].detail == "146 BPM; darkpsy vai de 140 a 155"


def test_tempo_overlap_shares():
    dist = tempo_source("psytrance", 138).distribution
    assert dist["progressive psytrance"] > 0
    assert dist["offbeat"] > 0


def test_tempo_half_time_read_as_double():
    source = tempo_source("psytrance", 72)
    assert source is not None
    assert source.distribution["full-on"] > 0
    assert "dobro" in source.evidence[0].detail


def test_tempo_zero_abstains():
    assert tempo_source("psytrance", 0) is None
    assert tempo_source("psytrance", None) is None
    assert tempo_source("psytrance", 20) is None


def test_artist_only_is_unsure():
    result = blend("psytrance", artist_tags=[Tag("full-on")], track_tags=[])
    assert result.unsure
    assert result.lean == "full-on"
    assert result.subgenre is None


def test_track_tags_and_tempo_agree_is_confident():
    # 100 BPM só cabe em psychill, então não há empate na fonte de tempo.
    result = blend("psytrance", artist_tags=[], track_tags=[Tag("psychill")], bpm=100)
    assert result.lean == "psychill"
    assert result.subgenre == "psychill"
    assert not result.unsure
    assert result.confidence >= subgenre.UNSURE_MIN_SHARE
    assert {e.source for e in result.evidence} == {"track_tags", "tempo"}


def test_sources_disagree_is_unsure():
    result = blend("psytrance", artist_tags=[], track_tags=[Tag("darkpsy")], bpm=132)
    assert result.unsure
    assert result.subgenre is None


def test_tempo_separates_two_tracks_by_same_artist():
    artist = [Tag("psytrance")]  # só o gênero: a carreira não diz o subgênero
    slow = blend("psytrance", artist_tags=artist, track_tags=[], bpm=132)
    fast = blend("psytrance", artist_tags=artist, track_tags=[], bpm=152)
    assert slow.lean != fast.lean
    assert slow.lean == "progressive psytrance"
    assert fast.lean == "darkpsy"


def test_rock_track_tag_only_behaves():
    result = blend("rock", artist_tags=[], track_tags=[Tag("hard rock")])
    assert result.subgenre == "hard rock"
    assert not result.unsure


def test_genre_without_subgenres_is_empty():
    assert blend("jazz-nada", artist_tags=[Tag("x")], track_tags=[], bpm=120) == EMPTY_RESULT
    assert blend(None, artist_tags=[Tag("full-on")], track_tags=[]) == EMPTY_RESULT


def test_no_votes_is_empty_not_unsure():
    result = blend("psytrance", artist_tags=[Tag("brasil")], track_tags=[], bpm=None)
    assert result == EMPTY_RESULT
    assert not result.unsure


def test_extra_source_is_combined():
    extra = SourceResult("audio", {"forest psy": 1.0}, [subgenre.Evidence("audio", "forest psy", "modelo de áudio")])
    result = blend("psytrance", artist_tags=[], track_tags=[Tag("psychill")], extra=[extra])
    shares = _shares(result)
    assert shares["forest psy"] > 0 and shares["psychill"] > 0
    assert any(e.source == "audio" for e in result.evidence)


def test_weak_goa_loses_to_real_signal():
    result = blend("psytrance", artist_tags=[Tag("goa")], track_tags=[Tag("full-on")])
    assert result.lean == "full-on"


def test_tags_source_ignores_other_genres_and_abstains():
    assert tags_source("track_tags", "psytrance", [Tag("hard rock")]) is None
    source = tags_source("track_tags", "psytrance", [Tag("goa", 100), Tag("full-on", 100)])
    assert source.distribution["full-on"] > source.distribution["goa trance"]
