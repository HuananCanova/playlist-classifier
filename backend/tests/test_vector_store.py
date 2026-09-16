"""Busca semântica: o que ela promete e o que ela não pode deixar vazar.

Os embeddings rodam de verdade aqui (ONNX local, sem rede depois do primeiro
download), então isto testa a busca real e não um dublê dela.
"""
import pytest

DONO = "usuario-a"
OUTRO = "usuario-b"

FAIXAS = [
    dict(track_id="t1", nome="Space Song", artistas=["Beach House"], album="Depression Cherry",
         tags=["dream pop", "shoegaze", "melancholic", "ethereal", "dreamy"]),
    dict(track_id="t2", nome="Sugar for the Pill", artistas=["Slowdive"], album="Slowdive",
         tags=["shoegaze", "dream pop", "atmospheric", "guitar", "melancholic"]),
    dict(track_id="t3", nome="One More Time", artistas=["Daft Punk"], album="Discovery",
         tags=["french house", "dance", "electronic", "upbeat", "disco", "party"]),
    dict(track_id="t4", nome="Around the World", artistas=["Daft Punk"], album="Homework",
         tags=["french house", "electronic", "dance", "groove"]),
    dict(track_id="t5", nome="Master of Puppets", artistas=["Metallica"], album="Master of Puppets",
         tags=["thrash metal", "heavy metal", "aggressive", "fast"]),
]


@pytest.mark.asyncio
async def test_indexa_e_encontra_por_sentido(chroma_tmp):
    assert await chroma_tmp.index_tracks(DONO, FAIXAS) == len(FAIXAS)
    assert (await chroma_tmp.stats(DONO))["faixas_indexadas"] == len(FAIXAS)

    # Nenhuma faixa tem a palavra "dance floor" nas tags; o vizinho certo tem
    # que sair do sentido, não da string.
    hits = await chroma_tmp.search(DONO, "energetic dance floor", limite=2)
    assert {h["track_id"] for h in hits} <= {"t3", "t4"}

    hits = await chroma_tmp.search(DONO, "aggressive and heavy", limite=1)
    assert hits[0]["track_id"] == "t5"


@pytest.mark.asyncio
async def test_recorte_por_ids_nao_vaza(chroma_tmp):
    """O recorte é o que impede o chat de escopo fixo de ver faixas de fora.

    Mesmo pedindo algo que casa perfeitamente com t1/t2, só os ids permitidos
    podem voltar.
    """
    await chroma_tmp.index_tracks(DONO, FAIXAS)
    permitidos = ["t3", "t4", "t5"]

    hits = await chroma_tmp.search(DONO, "melancholic dream pop", limite=5, track_ids=permitidos)

    assert hits, "o recorte não deveria zerar a busca"
    assert all(h["track_id"] in permitidos for h in hits)


@pytest.mark.asyncio
async def test_parecidas_nao_devolvem_a_propria_faixa(chroma_tmp):
    await chroma_tmp.index_tracks(DONO, FAIXAS)
    hits = await chroma_tmp.similar_to_track(DONO, "t1", limite=3)

    assert all(h["track_id"] != "t1" for h in hits)
    # A vizinha óbvia de Space Song é a outra faixa de shoegaze.
    assert hits[0]["track_id"] == "t2"


@pytest.mark.asyncio
async def test_faixa_fora_do_indice_devolve_vazio(chroma_tmp):
    await chroma_tmp.index_tracks(DONO, FAIXAS)
    assert await chroma_tmp.similar_to_track(DONO, "nao-existe") == []


@pytest.mark.asyncio
async def test_reindexar_atualiza_em_vez_de_duplicar(chroma_tmp):
    await chroma_tmp.index_tracks(DONO, FAIXAS)
    await chroma_tmp.index_tracks(DONO, FAIXAS)
    assert (await chroma_tmp.stats(DONO))["faixas_indexadas"] == len(FAIXAS)


@pytest.mark.asyncio
async def test_busca_vazia_e_indice_vazio(chroma_tmp):
    assert await chroma_tmp.search(DONO, "qualquer coisa") == []
    await chroma_tmp.index_tracks(DONO, FAIXAS)
    assert await chroma_tmp.search(DONO, "   ") == []


@pytest.mark.asyncio
async def test_uma_conta_nao_ve_o_acervo_da_outra(chroma_tmp):
    """A separação por conta é a razão de o índice ter dono.

    O acervo é o mesmo em conteúdo, então uma busca que casa perfeitamente com
    as faixas da conta A não pode devolver nada para a conta B.
    """
    await chroma_tmp.index_tracks(DONO, FAIXAS)

    assert await chroma_tmp.search(OUTRO, "melancholic dream pop", limite=5) == []
    assert (await chroma_tmp.stats(OUTRO))["faixas_indexadas"] == 0
    assert await chroma_tmp.all_metadata(OUTRO) == (0, [])

    # E o caminho por embedding, que varre a coleção inteira, também respeita.
    assert await chroma_tmp.similar_to_track(OUTRO, "t1", limite=3) == []


@pytest.mark.asyncio
async def test_mesma_faixa_em_duas_contas_nao_se_sobrescreve(chroma_tmp):
    """Duas pessoas podem ter a mesma música.

    Com o id do documento sendo só o id da faixa, o `upsert` da segunda conta
    apagava a da primeira — e A perdia a faixa da própria busca.
    """
    await chroma_tmp.index_tracks(DONO, FAIXAS)
    await chroma_tmp.index_tracks(OUTRO, FAIXAS[:2])

    assert (await chroma_tmp.stats(DONO))["faixas_indexadas"] == len(FAIXAS)
    assert (await chroma_tmp.stats(OUTRO))["faixas_indexadas"] == 2

    for dono in (DONO, OUTRO):
        hits = await chroma_tmp.search(dono, "melancholic dream pop", limite=1)
        assert hits and hits[0]["track_id"] in {"t1", "t2"}


@pytest.mark.asyncio
async def test_indice_antigo_e_adotado_sem_reindexar(chroma_tmp):
    """Documentos gravados antes do dono existir continuam encontráveis.

    Reindexar significaria reanalisar playlists no Spotify; a migração
    reaproveita o embedding já gravado e não sai para a rede.
    """
    col = await chroma_tmp._get_collection()
    # Como era antes: id da faixa puro, metadados sem `owner`.
    await chroma_tmp.asyncio.to_thread(
        col.upsert,
        ids=["t1"],
        documents=["Space Song Beach House dream pop shoegaze melancholic"],
        metadatas=[{"nome": "Space Song", "artistas": "Beach House", "album": "", "tags": "dream pop"}],
    )

    hits = await chroma_tmp.search(DONO, "melancholic dream pop", limite=3)

    assert [h["track_id"] for h in hits] == ["t1"]
    assert (await chroma_tmp.stats(DONO))["faixas_indexadas"] == 1
