"""A varredura que preenche o índice.

O que importa aqui não é indexar — isso `test_vector_store.py` já cobre — e sim
não reindexar. Uma varredura que refizesse todas as playlists a cada execução
gastaria chamadas do Spotify à toa numa conta com histórico de bloqueio, e é
exatamente esse o cuidado que o `snapshot_id` implementa.
"""
import json

import pytest

from app import indexer


@pytest.fixture
def estado_tmp(tmp_path, monkeypatch):
    """Isola o arquivo de estado para não escrever no índice real."""
    monkeypatch.setattr(indexer, "ESTADO", tmp_path / "indexed_playlists.json")
    return indexer.ESTADO


def _pl(pid: str, snapshot: str) -> dict:
    return {"id": pid, "name": f"Playlist {pid}", "snapshot_id": snapshot}


def test_playlist_nunca_vista_esta_pendente():
    playlists = [_pl("a", "s1"), _pl("b", "s1")]
    assert indexer._pendentes(playlists, {}) == playlists


def test_playlist_ja_indexada_e_intacta_e_pulada():
    playlists = [_pl("a", "s1"), _pl("b", "s1")]
    estado = {"a": "s1", "b": "s1"}
    assert indexer._pendentes(playlists, estado) == []


def test_playlist_alterada_volta_para_a_fila():
    """O snapshot_id do Spotify muda quando o conteúdo muda.

    É esse sinal que faz uma playlist editada ser reindexada sem obrigar a
    varredura a refazer todas as outras.
    """
    playlists = [_pl("a", "s2"), _pl("b", "s1")]
    estado = {"a": "s1", "b": "s1"}

    pendentes = indexer._pendentes(playlists, estado)

    assert [p["id"] for p in pendentes] == ["a"]


def test_playlist_sem_snapshot_nao_quebra():
    """Nem toda resposta traz snapshot_id; a ausência não pode virar KeyError."""
    playlists = [{"id": "a", "name": "Sem snapshot"}]

    assert indexer._pendentes(playlists, {}) == playlists
    assert indexer._pendentes(playlists, {"a": "sem-snapshot"}) == []


def test_estado_sobrevive_a_ida_e_volta(estado_tmp):
    indexer._salvar_estado({"a": "s1", "b": "s2"})
    assert indexer._carregar_estado() == {"a": "s1", "b": "s2"}


def test_estado_corrompido_e_tratado_como_vazio(estado_tmp):
    """Um arquivo corrompido deve custar uma reindexação, não uma exceção."""
    estado_tmp.parent.mkdir(parents=True, exist_ok=True)
    estado_tmp.write_text("{isso nao e json", encoding="utf-8")

    assert indexer._carregar_estado() == {}


def test_estado_ausente_e_vazio(estado_tmp):
    assert not estado_tmp.exists()
    assert indexer._carregar_estado() == {}


@pytest.mark.asyncio
async def test_nao_dispara_duas_varreduras(monkeypatch, estado_tmp, tmp_path):
    """Uma varredura por vez.

    A busca e o perfil disparam a mesma varredura; as duas entradas não podem
    virar duas varreduras concorrentes sobre a mesma conta.
    """
    import asyncio

    from app import profile_store

    monkeypatch.setattr(profile_store, "STORE_PATH", tmp_path / "profile")
    profile_store.clear_memo()
    chamadas = []

    async def fake_rodar(refresh_token, fila):
        chamadas.append(refresh_token)
        # Fica "rodando" o suficiente para a segunda chamada encontrar a
        # primeira em andamento.
        await asyncio.sleep(0.2)

    monkeypatch.setattr(indexer, "_rodar", fake_rodar)
    monkeypatch.setattr(indexer, "_progress", indexer.IndexProgress())

    playlists = [{**_pl("a", "s1"), "track_count": 3}]
    primeira = await indexer.start("refresh-token", playlists)
    # `create_task` só agenda; sem devolver o controle ao loop, a corrotina
    # ainda não rodou e `chamadas` estaria vazia por tempo, não por lógica.
    await asyncio.sleep(0)

    segunda = await indexer.start("refresh-token", playlists)

    assert primeira.running
    assert segunda is primeira, "a segunda chamada deveria devolver a varredura em curso"
    assert len(chamadas) == 1, "a segunda chamada não pode iniciar outra varredura"

    await indexer.cancel()


def test_progresso_serializa_para_a_api():
    """O modelo `IndexStatus` é montado com `**progress_dict()`."""
    from app.models import IndexStatus

    status = IndexStatus(**indexer.progress_dict())
    assert isinstance(status.running, bool)
    assert isinstance(status.errors, list)


# ── ritmo e bloqueio ─────────────────────────────────────────────────────────

def _erro_429(retry_after: str):
    import httpx

    request = httpx.Request("GET", "https://api.spotify.com/v1/playlists/x/items")
    response = httpx.Response(429, headers={"Retry-After": retry_after}, request=request)
    return httpx.HTTPStatusError("429", request=request, response=response)


@pytest.fixture
def varredura_fake(monkeypatch, estado_tmp, tmp_path):
    """Varredura sem rede: token falso, sem pausas, e `_indexar_uma` programável."""
    from app import profile_store

    monkeypatch.setattr(profile_store, "STORE_PATH", tmp_path / "profile")
    profile_store.clear_memo()
    monkeypatch.setattr(indexer, "PAUSA_ENTRE_PLAYLISTS", 0)
    monkeypatch.setattr(indexer, "_progress", indexer.IndexProgress())

    async def token(_):
        return "tok"

    monkeypatch.setattr(indexer, "access_token_from_refresh_token", token)
    esperas = []

    async def esperar(segundos):
        esperas.append(segundos)

    monkeypatch.setattr(indexer, "_esperar", esperar)
    return esperas


def _conta(n=4):
    return [{"id": f"p{i}", "name": f"P{i}", "snapshot_id": "s", "track_count": 10 + i} for i in range(n)]


@pytest.mark.asyncio
async def test_bloqueio_longo_para_tudo_e_sobrevive_ao_reinicio(monkeypatch, varredura_fake, spotify_state_tmp):
    chamadas = []

    async def indexar(token, playlist):
        chamadas.append(playlist["id"])
        # O que o spotify_client faz ao receber a resposta: grava o bloqueio.
        spotify_state_tmp._set_global_block(65527)
        raise _erro_429("65527")

    monkeypatch.setattr(indexer, "_indexar_uma", indexar)

    await indexer.start("r", _conta())
    await indexer._task

    assert chamadas == ["p0"], "depois do primeiro bloqueio longo nenhuma playlist pode ser tentada"
    assert indexer.progress_dict()["blocked_seconds"] > 60_000

    # "Reinício": memória zerada, bloqueio lido do disco — não começa de novo.
    monkeypatch.setattr(spotify_state_tmp, "_global_until", None)
    monkeypatch.setattr(indexer, "_progress", indexer.IndexProgress())
    progresso = await indexer.start("r", _conta())
    assert not progresso.running
    assert chamadas == ["p0"]


@pytest.mark.asyncio
async def test_espera_curta_repete_a_mesma_playlist(monkeypatch, varredura_fake):
    tentativas = []

    async def indexar(token, playlist):
        tentativas.append(playlist["id"])
        if playlist["id"] == "p0" and tentativas.count("p0") == 1:
            raise _erro_429("3")
        return 10

    monkeypatch.setattr(indexer, "_indexar_uma", indexar)

    await indexer.start("r", _conta(2))
    await indexer._task

    # Antes, um 429 curto pulava a playlist até a próxima varredura.
    assert tentativas == ["p0", "p0", "p1"]
    assert varredura_fake == [3.0]
    assert indexer.progress_dict()["done"] == 2
    assert indexer._carregar_estado() == {"p0": "s", "p1": "s"}


@pytest.mark.asyncio
async def test_teto_por_hora_espera_em_vez_de_acelerar(monkeypatch, varredura_fake):
    async def indexar(token, playlist):
        return 1

    monkeypatch.setattr(indexer, "_indexar_uma", indexar)
    monkeypatch.setattr(indexer, "MAX_PLAYLISTS_POR_HORA", 2)

    await indexer.start("r", _conta(3))
    await indexer._task

    assert indexer.progress_dict()["done"] == 3
    assert len(varredura_fake) == 1 and varredura_fake[0] > 3500


def test_cobertura_nao_chama_o_spotify(estado_tmp, tmp_path, monkeypatch):
    from app import profile_store

    monkeypatch.setattr(profile_store, "STORE_PATH", tmp_path / "profile")
    profile_store.clear_memo()
    cobertura = indexer.coverage(_conta(2) + [{"id": "vazia", "name": "V", "track_count": 0}])
    assert cobertura == {
        "total_playlists": 2,
        "indexed_playlists": 0,
        "pending_playlists": 2,
        "estimated_calls": 4,
    }
