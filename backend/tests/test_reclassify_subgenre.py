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


def test_reclassify_is_idempotent():
    evidence_store.put(TrackEvidence("t1", artist_tags=[Tag("darkpsy", 100)], track_tags=[], bpm=146.0))
    analise = _analise(_faixa("t1"), _faixa("t2"))
    primeira = reclassify.analysis(analise)
    # O script só reclassifica o que não está atual: a segunda passada não toca em nada.
    assert reclassify.is_current(primeira) is True
    segunda = primeira if reclassify.is_current(primeira) else reclassify.analysis(primeira)
    assert segunda.model_dump() == primeira.model_dump()
    # E o selo sobrevive a gravar e ler do banco.
    assert reclassify.is_current(PlaylistAnalysis.model_validate_json(primeira.model_dump_json())) is True

    resumo, _ = reclassify.digest(
        {"tracks": [{"id": "t1", "genres": ["darkpsy"], "tags": ["darkpsy"]}, {"id": "t2", "genres": ["darkpsy"], "tags": ["darkpsy"]}]}
    )
    assert reclassify.is_current(resumo) is True


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
