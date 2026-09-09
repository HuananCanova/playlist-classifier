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
async def test_nao_dispara_duas_varreduras(monkeypatch):
    """Uma varredura por vez.

    O app chama isto sozinho ao abrir e o usuário pode clicar no botão; as duas
    entradas não podem virar duas varreduras concorrentes sobre a mesma conta.
    """
    import asyncio

    chamadas = []

    async def fake_rodar(refresh_token):
        chamadas.append(refresh_token)
        # Fica "rodando" o suficiente para a segunda chamada encontrar a
        # primeira em andamento.
        await asyncio.sleep(0.2)

    monkeypatch.setattr(indexer, "_rodar", fake_rodar)
    monkeypatch.setattr(indexer, "_progress", indexer.IndexProgress())

    primeira = await indexer.start("refresh-token")
    # `create_task` só agenda; sem devolver o controle ao loop, a corrotina
    # ainda não rodou e `chamadas` estaria vazia por tempo, não por lógica.
    await asyncio.sleep(0)

    segunda = await indexer.start("refresh-token")

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
