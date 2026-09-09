"""Busca semântica: o que ela promete e o que ela não pode deixar vazar.

Os embeddings rodam de verdade aqui (ONNX local, sem rede depois do primeiro
download), então isto testa a busca real e não um dublê dela.
"""
import pytest

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
    assert await chroma_tmp.index_tracks(FAIXAS) == len(FAIXAS)
    assert (await chroma_tmp.stats())["faixas_indexadas"] == len(FAIXAS)

    # Nenhuma faixa tem a palavra "dance floor" nas tags; o vizinho certo tem
    # que sair do sentido, não da string.
    hits = await chroma_tmp.search("energetic dance floor", limite=2)
    assert {h["track_id"] for h in hits} <= {"t3", "t4"}

    hits = await chroma_tmp.search("aggressive and heavy", limite=1)
    assert hits[0]["track_id"] == "t5"


@pytest.mark.asyncio
async def test_recorte_por_ids_nao_vaza(chroma_tmp):
    """O recorte é o que impede o chat de escopo fixo de ver faixas de fora.

    Mesmo pedindo algo que casa perfeitamente com t1/t2, só os ids permitidos
    podem voltar.
    """
    await chroma_tmp.index_tracks(FAIXAS)
    permitidos = ["t3", "t4", "t5"]

    hits = await chroma_tmp.search("melancholic dream pop", limite=5, track_ids=permitidos)

    assert hits, "o recorte não deveria zerar a busca"
    assert all(h["track_id"] in permitidos for h in hits)


@pytest.mark.asyncio
async def test_parecidas_nao_devolvem_a_propria_faixa(chroma_tmp):
    await chroma_tmp.index_tracks(FAIXAS)
    hits = await chroma_tmp.similar_to_track("t1", limite=3)

    assert all(h["track_id"] != "t1" for h in hits)
    # A vizinha óbvia de Space Song é a outra faixa de shoegaze.
    assert hits[0]["track_id"] == "t2"


@pytest.mark.asyncio
async def test_faixa_fora_do_indice_devolve_vazio(chroma_tmp):
    await chroma_tmp.index_tracks(FAIXAS)
    assert await chroma_tmp.similar_to_track("nao-existe") == []


@pytest.mark.asyncio
async def test_reindexar_atualiza_em_vez_de_duplicar(chroma_tmp):
    await chroma_tmp.index_tracks(FAIXAS)
    await chroma_tmp.index_tracks(FAIXAS)
    assert (await chroma_tmp.stats())["faixas_indexadas"] == len(FAIXAS)


@pytest.mark.asyncio
async def test_busca_vazia_e_indice_vazio(chroma_tmp):
    assert await chroma_tmp.search("qualquer coisa") == []
    await chroma_tmp.index_tracks(FAIXAS)
    assert await chroma_tmp.search("   ") == []
