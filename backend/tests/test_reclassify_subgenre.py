"""Reclassificação offline: subgênero a partir da evidência guardada."""
import json

from app import analysis_store, db, evidence_store, profile_store, reclassify
from app.evidence_store import TrackEvidence
from app.models import PlaylistAnalysis, PlaylistSummary, TrackGenreInfo
from app.taxonomy import Tag


def _faixa(track_id="t1", **extra) -> TrackGenreInfo:
    base = dict(
        track_id=track_id,
        name="Faixa",
        artists=["Artista"],
        duration_ms=1000,
        genres=["darkpsy"],
        subgenre_tags=["darkpsy"],
        bpm=None,
    )
    return TrackGenreInfo(**{**base, **extra})


def _analise(*faixas) -> PlaylistAnalysis:
    return PlaylistAnalysis(
        playlist=PlaylistSummary(id="p1", name="Playlist", track_count=len(faixas)),
        tracks=list(faixas),
        genre_distribution=[],
        subgenre_distribution=[],
        top_artists=[],
        bpm_histogram=[],
        tracks_missing_genre=0,
    )


def test_reclassify_with_evidence_uses_tempo():
    ev = TrackEvidence("t1", artist_tags=[Tag("darkpsy", 100)], track_tags=[], bpm=146.0)
    nova = reclassify.track(_faixa(), ev)

    assert nova.genre == "psytrance"
    assert nova.bpm is None  # o que vem do Deezer na análise não é tocado
    assert nova.subgenre_blend
    assert any(e.source == "tempo" for e in nova.subgenre_evidence)


def test_reclassify_without_evidence_is_tag_only():
    nova = reclassify.track(_faixa(bpm=None), None)

    assert nova.genre == "psytrance"
    assert nova.subgenre_unsure is True
    assert nova.subgenre is None
    assert {e.source for e in nova.subgenre_evidence} <= {"artist_tags"}


def test_old_digest_gets_subgenre_fields():
    velho = {"tracks": [{"id": "t1", "genres": ["darkpsy"], "tags": ["darkpsy"], "bpm": None}]}
    assert reclassify.is_current(velho) is False

    novo, _ = reclassify.digest(velho)
    faixa = novo["tracks"][0]
    assert {"subgenre_lean", "subgenre_unsure", "subgenre_blend"} <= set(faixa)
    assert faixa["subgenre_unsure"] is True
    assert reclassify.is_current(novo) is True


def test_old_digest_uses_stored_evidence():
    evidence_store.put(TrackEvidence("t1", artist_tags=[], track_tags=[Tag("darkpsy", 100)], bpm=146.0))
    velho = {"tracks": [{"id": "t1", "genres": ["darkpsy"], "tags": ["darkpsy"], "bpm": None}]}
    novo, _ = reclassify.digest(velho)
    assert novo["tracks"][0]["subgenre_blend"]


def test_old_analysis_is_not_current_until_reclassified():
    analise = _analise(_faixa())
    assert reclassify.is_current(analise) is False
    nova = reclassify.analysis(analise)
    assert reclassify.is_current(nova) is True
    assert nova.subgenre_bars
    # Sem evidência a faixa é só-artista, então toda a barra é "incerta".
    assert all(b.confident == 0 for b in nova.subgenre_bars)
    # Depois de ir e voltar do banco continua atual.
    volta = PlaylistAnalysis.model_validate_json(nova.model_dump_json())
    assert reclassify.is_current(volta) is True


def test_is_current_survives_reclassification_and_roundtrip():
    analise = _analise(_faixa("t1"))
    nova = reclassify.analysis(analise)
    assert reclassify.is_current(nova) is True
    assert reclassify.is_current(PlaylistAnalysis.model_validate_json(nova.model_dump_json())) is True
    resumo, _ = reclassify.digest(
        {"tracks": [{"id": "t1", "genres": ["darkpsy"], "tags": ["darkpsy"]}]}
    )
    assert reclassify.is_current(resumo) is True


def _grava(faixas_analise, faixas_resumo):
    analysis_store.save(_analise(*faixas_analise), has_audio=False)
    db.execute(
        "INSERT INTO playlist_digests (playlist_id, snapshot_id, has_audio, format, digest, saved_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("p1", None, 0, profile_store.VERSION,
         json.dumps({"playlist": {"id": "p1"}, "tracks": faixas_resumo}), 1.0),
    )


def _linhas():
    a = db.query_one("SELECT analysis FROM playlist_analyses WHERE playlist_id = 'p1'")["analysis"]
    d = json.loads(db.query_one("SELECT digest FROM playlist_digests WHERE playlist_id = 'p1'")["digest"])
    d.pop("saved_at", None)
    return a, d


def test_account_twice_changes_nothing_the_second_time():
    _grava(
        [_faixa("t1"), _faixa("t2")],
        [{"id": t, "genres": ["darkpsy"], "tags": ["darkpsy"]} for t in ("t1", "t2")],
    )
    evidence_store.put(TrackEvidence("t1", artist_tags=[Tag("darkpsy", 100)], track_tags=[], bpm=146.0))

    reclassify.account(["p1"])
    primeira = _linhas()
    reclassify.account(["p1"])
    assert _linhas() == primeira


def test_account_leaves_evidenceless_tracks_of_a_current_row_alone():
    atual = reclassify.analysis(_analise(_faixa("t1"), _faixa("t2")))
    # Valores que um reprocessamento do balaio não reproduziria.
    marcada = atual.tracks[1].model_copy(
        update={"genre": "psytrance", "genre_evidence": ["fixo"], "subgenre_tags": ["fixo", "darkpsy"]}
    )
    atual = atual.model_copy(update={"tracks": [atual.tracks[0], marcada]})
    analysis_store.save(atual, has_audio=False)
    evidence_store.put(TrackEvidence("t1", artist_tags=[], track_tags=[Tag("darkpsy", 100)], bpm=146.0))

    reclassify.account(["p1"])

    row = db.query_one("SELECT analysis FROM playlist_analyses WHERE playlist_id = 'p1'")
    depois = PlaylistAnalysis.model_validate_json(row["analysis"])
    t1, t2 = depois.tracks
    assert (t2.genre, t2.genre_evidence, t2.subgenre_tags) == ("psytrance", ["fixo"], ["fixo", "darkpsy"])
    assert t1.subgenre_blend  # a com evidência foi refeita
    assert depois.subgenre_bars  # e as barras foram recontadas


def test_account_rewrites_stored_rows():
    analise = _analise(_faixa("t1"))
    analysis_store.save(analise, has_audio=False)
    db.execute(
        "INSERT INTO playlist_digests (playlist_id, snapshot_id, has_audio, format, digest, saved_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("p1", None, 0, profile_store.VERSION,
         json.dumps({"playlist": {"id": "p1"}, "tracks": [{"id": "t1", "genres": ["darkpsy"], "tags": ["darkpsy"]}]}), 1.0),
    )
    evidence_store.put(TrackEvidence("t1", artist_tags=[], track_tags=[Tag("darkpsy", 100)], bpm=146.0))

    contagem = reclassify.account(["p1", "inexistente"])

    assert contagem == {"analyses": 1, "digests": 1}
    profile_store.clear_memo()
    assert profile_store.load("p1")["tracks"][0]["subgenre_blend"]
    row = db.query_one("SELECT analysis FROM playlist_analyses WHERE playlist_id = 'p1'")
    assert PlaylistAnalysis.model_validate_json(row["analysis"]).tracks[0].subgenre_blend


def test_reclassify_with_evidence_orders_tags_by_weight():
    # 14 tags: as 12 leves vêm antes no alfabeto, mas as pesadas não podem cair no corte.
    leves = [Tag(f"aaa{i:02d}", 5.0) for i in range(12)]
    ev = TrackEvidence("t1", artist_tags=[Tag("psytrance", 100), Tag("trance", 90), *leves], track_tags=[])

    nova = reclassify.track(_faixa(), ev)
    assert nova.subgenre_tags[:2] == ["psytrance", "trance"]

    evidence_store.put(ev)
    resumo, _ = reclassify.digest({"tracks": [{"id": "t1", "genres": [], "tags": [], "bpm": None}]})
    assert resumo["tracks"][0]["tags"][:2] == ["psytrance", "trance"]


def test_reclassify_without_evidence_keeps_alphabetical_tags():
    nova = reclassify.track(_faixa(genres=["psytrance"], subgenre_tags=["zebra", "darkpsy"]), None)
    assert nova.subgenre_tags == ["darkpsy", "psytrance", "zebra"]


# ── selo guardado na evidência ───────────────────────────────────────────────


def _ev_psy(**extra):
    return TrackEvidence("t1", artist_tags=[Tag("psytrance", 100)], track_tags=[], **extra)


def test_reclassify_mapped_label_agreeing_with_track_tags_is_confident():
    ev = TrackEvidence(
        "t1", artist_tags=[Tag("psytrance", 100)], track_tags=[Tag("full-on", 80)],
        label="Dacru Records", label_checked_at=1.0,
    )
    nova = reclassify.track(_faixa(), ev)

    assert nova.subgenre == "full-on" and nova.subgenre_unsure is False
    assert any(e.source == "label" and e.says == "full-on" for e in nova.subgenre_evidence)


def test_reclassify_label_alone_leans_but_stays_unsure():
    nova = reclassify.track(_faixa(), _ev_psy(label="Parvati Records", label_checked_at=1.0))

    assert nova.subgenre_lean == "forest psy"
    assert nova.subgenre_unsure is True and nova.subgenre is None


def test_reclassify_unknown_label_is_same_as_no_label():
    com = reclassify.track(_faixa(), _ev_psy(label="Kontor Records", label_checked_at=1.0))
    sem = reclassify.track(_faixa(), _ev_psy())
    assert com == sem


def test_subgenre_of_uses_stored_label():
    r = reclassify.subgenre_of(_faixa(genre="psytrance"), _ev_psy(label="Suntrip Records", label_checked_at=1.0), None)
    assert r.lean == "goa trance"


def test_digest_uses_stored_label():
    evidence_store.put(_ev_psy(label="Parvati Records", label_checked_at=1.0))
    novo, _ = reclassify.digest({"tracks": [{"id": "t1", "genres": ["psytrance"], "tags": ["psytrance"]}]})
    assert novo["tracks"][0]["subgenre_lean"] == "forest psy"
