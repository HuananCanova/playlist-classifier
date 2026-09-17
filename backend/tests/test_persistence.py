"""Persistência: banco, dados por faixa e análises guardadas.

O que se protege aqui é o motivo de o banco existir — não repetir chamadas ao
Spotify, Last.fm e Deezer — sem abrir mão de duas garantias: uma falha externa
nunca fica guardada como resposta, e uma análise guardada só sai para a conta
que tem a playlist na listagem.
"""
import json
import time

import httpx
import pytest

from app import analysis_store, db, deezer_client, enrichment_store, genre_analysis, lastfm_client, playlists, profile_store
from app.cache import artist_tags_cache, deezer_track_cache, playlist_analysis_cache, user_playlists_cache
from app.models import PlaylistAnalysis, PlaylistSummary, TrackGenreInfo


class FakeRequest:
    def __init__(self, user_id="eu"):
        self.session = {"access_token": "tok", "expires_at": time.time() + 3600, "me": {"id": user_id}}


def _summary(pid="p1", snapshot="s1"):
    return PlaylistSummary(id=pid, name="Mistura", track_count=1, snapshot_id=snapshot)


def _analysis(pid="p1", snapshot="s1", bpm=None, preview=None, deezer_id=None):
    return PlaylistAnalysis(
        playlist=_summary(pid, snapshot),
        tracks=[
            TrackGenreInfo(
                track_id="t1", name="Um", artists=["A"], duration_ms=1000, genres=["rock"],
                subgenre_tags=["britpop", "rock"], bpm=bpm, preview_url=preview, deezer_id=deezer_id,
            )
        ],
        genre_distribution=[], subgenre_distribution=[], top_artists=[], bpm_histogram=[],
        tracks_missing_genre=0,
    )


class Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erro", request=None, response=None)


class FakeClient:
    """Responde por uma função (url, params) -> Resp e conta as chamadas."""

    def __init__(self, responder):
        self.responder = responder
        self.calls = 0

    async def get(self, url, params=None, **_):
        self.calls += 1
        return self.responder(url, params or {})


# ── banco ────────────────────────────────────────────────────────────────────


def test_migracoes_aplicadas_e_idempotentes(db_tmp, tmp_path):
    assert db.query_one("PRAGMA user_version")[0] == len(db.MIGRATIONS)
    db.close()  # reabrir o mesmo arquivo não reaplica nada
    assert db.query_one("PRAGMA user_version")[0] == len(db.MIGRATIONS)


def test_dado_externo_expira(monkeypatch):
    enrichment_store.put_artist_tags("slowdive", ["shoegaze"])
    assert enrichment_store.get_artist_tags("slowdive") == ["shoegaze"]

    agora = time.time()
    monkeypatch.setattr(enrichment_store.time, "time", lambda: agora + enrichment_store.TAGS_TTL + 1)
    assert enrichment_store.get_artist_tags("slowdive") is None


def test_faixa_nao_encontrada_no_deezer_expira_antes(monkeypatch):
    enrichment_store.put_deezer_match("a::achada", 1, 120.0, "http://dz")
    enrichment_store.put_deezer_match("a::perdida", None, None, None)

    agora = time.time()
    monkeypatch.setattr(enrichment_store.time, "time", lambda: agora + enrichment_store.DEEZER_MISS_TTL + 1)
    assert enrichment_store.get_deezer_match("a::achada") == {"deezer_id": 1, "bpm": 120.0, "deezer_url": "http://dz"}
    assert enrichment_store.get_deezer_match("a::perdida") is None


# ── Last.fm ──────────────────────────────────────────────────────────────────


async def test_tags_do_lastfm_vem_do_banco_depois_de_um_reinicio():
    client = FakeClient(lambda url, p: Resp({"toptags": {"tag": [{"name": "shoegaze"}]}}))

    assert await lastfm_client.get_artist_tags(client, "Slowdive") == ["shoegaze"]
    artist_tags_cache.clear()  # outro processo
    assert await lastfm_client.get_artist_tags(client, "Slowdive") == ["shoegaze"]
    assert client.calls == 1


@pytest.mark.parametrize("erro, guardado", [(6, []), (29, None), (11, None)])
async def test_so_nao_encontrado_do_lastfm_fica_guardado(erro, guardado):
    client = FakeClient(lambda url, p: Resp({"error": erro, "message": "x"}))

    assert await lastfm_client.get_artist_tags(client, "Ninguém") == []
    assert enrichment_store.get_artist_tags("ninguém") == guardado


async def test_falha_de_rede_do_lastfm_nao_fica_nem_em_memoria():
    def falha(url, p):
        raise httpx.ConnectError("sem rede")

    client = FakeClient(falha)
    assert await lastfm_client.get_track_tags(client, "A", "Um") == []

    client.responder = lambda url, p: Resp({"toptags": {"tag": [{"name": "dream pop"}]}})
    assert await lastfm_client.get_track_tags(client, "A", "Um") == ["dream pop"]


# ── Deezer ───────────────────────────────────────────────────────────────────


def _deezer(url, params):
    if url.endswith("/search"):
        return Resp({"data": [{"id": 42, "title": "Um", "artist": {"name": "A"}, "preview": "http://p?exp=1", "link": "http://dz/42"}]})
    return Resp({"id": 42, "bpm": 128, "preview": "http://p?exp=2", "link": "http://dz/42"})


async def test_correspondencia_do_deezer_guardada_sem_a_previa():
    client = FakeClient(_deezer)
    primeira = await deezer_client.get_track_info(client, "A", "Um")
    assert primeira == {"deezer_id": 42, "bpm": 128.0, "preview_url": "http://p?exp=2", "deezer_url": "http://dz/42"}

    deezer_track_cache.clear()
    segunda = await deezer_client.get_track_info(client, "A", "Um")
    # A prévia assinada expira: do banco a faixa volta só com o id para resolvê-la.
    assert segunda == {"deezer_id": 42, "bpm": 128.0, "preview_url": None, "deezer_url": "http://dz/42"}
    assert client.calls == 2  # busca + detalhe, só na primeira vez


async def test_cota_estourada_do_deezer_nao_vira_faixa_inexistente():
    client = FakeClient(lambda url, p: Resp({"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}}))
    assert (await deezer_client.get_track_info(client, "A", "Um"))["deezer_id"] is None
    assert enrichment_store.get_deezer_match("a::um") is None


# ── análises guardadas ───────────────────────────────────────────────────────


def test_analise_guardada_sem_previa_e_presa_a_versao():
    analysis_store.save(_analysis(preview="http://p?exp=1", deezer_id=42), has_audio=True)

    stored = analysis_store.load("p1", "s1")
    assert stored.has_audio
    assert stored.analysis.tracks[0].preview_url is None
    assert stored.analysis.tracks[0].deezer_id == 42
    assert analysis_store.load("p1", "s2") is None


def test_analise_sem_audio_nao_apaga_a_com_audio_da_mesma_versao():
    analysis_store.save(_analysis(bpm=128.0), has_audio=True)
    analysis_store.save(_analysis(bpm=None), has_audio=False)
    assert analysis_store.load("p1", "s1").analysis.tracks[0].bpm == 128.0

    analysis_store.save(_analysis(snapshot="s2"), has_audio=False)
    assert analysis_store.load("p1", "s2").has_audio is False


def test_resumos_em_json_da_versao_anterior_sao_importados(tmp_path):
    legado = profile_store.STORE_PATH
    legado.mkdir(parents=True)
    digest = profile_store.digest_from_analysis(_analysis(pid="velha"), has_audio=False)
    (legado / "velha.json").write_text(json.dumps(digest), encoding="utf-8")
    (legado / "quebrado.json").write_text("{", encoding="utf-8")

    assert profile_store.load("velha")["playlist"]["id"] == "velha"
    profile_store.clear_memo()
    assert profile_store.load("velha") is not None  # agora do banco


# ── quem pode ver o quê ──────────────────────────────────────────────────────


@pytest.fixture
def fontes(monkeypatch):
    """Spotify, Last.fm e Deezer falsos, contando quem foi chamado."""
    chamadas = {"spotify": 0, "deezer": 0}

    class FakeSpotify:
        def __init__(self, token):
            pass

        async def get_playlist(self, client, pid):
            chamadas["spotify"] += 1
            return {"id": pid, "name": "Mistura", "snapshot_id": "s2", "images": []}

        async def get_all_playlist_tracks(self, client, pid):
            return [{"id": "t1", "name": "Um", "duration_ms": 1000, "artists": [{"name": "A"}], "album": {}}]

    async def tags(*args, **kwargs):
        return ["rock"]

    async def deezer_many(client, pairs):
        chamadas["deezer"] += 1
        return [{"deezer_id": 42, "bpm": 128.0, "preview_url": "http://p", "deezer_url": "http://dz"} for _ in pairs]

    monkeypatch.setattr(genre_analysis, "SpotifyClient", FakeSpotify)
    monkeypatch.setattr(genre_analysis, "get_artist_tags", tags)
    monkeypatch.setattr(genre_analysis, "get_track_tags", tags)
    monkeypatch.setattr(genre_analysis, "get_deezer_many", deezer_many)
    return chamadas


def _listagem(request, *summaries):
    analysis_store.save_listing(playlists._user_cache_key(request), list(summaries))


async def test_playlist_da_listagem_sai_do_banco_sem_chamar_ninguem(fontes):
    request = FakeRequest()
    _listagem(request, _summary("p1", "s1"))
    analysis_store.save(_analysis(bpm=128.0), has_audio=True)

    analysis, lida_agora = await playlists.analysis_for_user(request, "p1")

    assert not lida_agora and analysis.tracks[0].bpm == 128.0
    assert fontes == {"spotify": 0, "deezer": 0}
    # As ferramentas do chat, que leem pelo id, também não vão precisar do Spotify.
    assert playlist_analysis_cache["p1"] is analysis


async def test_playlist_fora_da_listagem_nunca_sai_do_banco(fontes):
    """Outra conta pedindo o id de uma playlist guardada: quem decide é o Spotify."""
    request = FakeRequest(user_id="outra")
    _listagem(request, _summary("dela", "s1"))
    analysis_store.save(_analysis(bpm=128.0), has_audio=True)
    playlist_analysis_cache["p1"] = _analysis(bpm=128.0)

    _, lida_agora = await playlists.analysis_for_user(request, "p1")

    assert lida_agora and fontes["spotify"] == 1


async def test_guardada_sem_audio_completa_so_com_o_deezer(fontes):
    request = FakeRequest()
    _listagem(request, _summary("p1", "s1"))
    analysis_store.save(_analysis(), has_audio=False)

    analysis, lida_agora = await playlists.analysis_for_user(request, "p1")

    assert not lida_agora
    assert fontes == {"spotify": 0, "deezer": 1}
    assert analysis.tracks[0].bpm == 128.0 and analysis.average_bpm == 128.0
    assert analysis_store.load("p1", "s1").has_audio


async def test_versao_nova_relida_e_listagem_atualizada(fontes):
    request = FakeRequest()
    _listagem(request, _summary("p1", "s1"))
    analysis_store.save(_analysis(snapshot="s0"), has_audio=True)

    analysis, lida_agora = await playlists.analysis_for_user(request, "p1")
    assert lida_agora and fontes["spotify"] == 1
    assert analysis.playlist.snapshot_id == "s2"

    # A listagem guardada passa a apontar a versão lida: a próxima visita sai do banco.
    user_playlists_cache.clear()
    playlist_analysis_cache.clear()
    _, de_novo = await playlists.analysis_for_user(request, "p1")
    assert not de_novo and fontes["spotify"] == 1


async def test_faixas_da_conta_saem_so_das_playlists_dela():
    """A base do isolamento da busca: as faixas de uma conta são as das
    playlists da listagem dela, e nada que outra conta tenha analisado."""
    minha = FakeRequest(user_id="eu")
    outra = FakeRequest(user_id="outra")
    _listagem(minha, _summary("p1", "s1"))
    _listagem(outra, _summary("dela", "s1"))

    profile_store.save(_analysis(pid="p1"), has_audio=False)
    dela = _analysis(pid="dela")
    dela.tracks[0].track_id = "t-privada"
    profile_store.save(dela, has_audio=False)

    assert await playlists.account_track_ids(minha) == ["t1"]
    assert await playlists.account_track_ids(outra) == ["t-privada"]
