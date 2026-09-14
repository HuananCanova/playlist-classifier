"""O agrupamento tem uma resposta certa quando os dados são construídos assim.

A fixture monta três blocos que não se misturam (shoegaze, french house,
thrash). Um k-means correto tem que reencontrá-los; se ele não consegue nem
isso, não vale nada numa playlist real.
"""
import pytest

from app.clustering import MIN_FAIXAS, cluster_playlist
from app.models import PlaylistAnalysis, PlaylistSummary


@pytest.mark.asyncio
async def test_reencontra_os_tres_blocos(analysis):
    r = await cluster_playlist(analysis)

    assert r.note is None
    assert r.k == 3
    assert len(r.clusters) == 3
    assert r.silhouette is not None and r.silhouette > 0.2

    # Cada grupo deve conter faixas de um bloco só.
    for c in r.clusters:
        blocos = {tid.split("-")[0] for tid in c.track_ids}
        assert len(blocos) == 1, f"grupo {c.label} misturou {blocos}"

    # E os três blocos precisam aparecer, um por grupo.
    encontrados = {c.track_ids[0].split("-")[0] for c in r.clusters}
    assert encontrados == {"shoegaze", "house", "metal"}


@pytest.mark.asyncio
async def test_rotulo_ignora_tag_comum_a_dois_grupos(analysis):
    """`guitar` está no bloco de shoegaze e no de metal.

    Como o rótulo sai da distinção e não da frequência, ela não deve nomear
    nenhum dos dois — é exatamente o caso que separa as duas estratégias.
    """
    r = await cluster_playlist(analysis)
    rotulos = " ".join(c.label for c in r.clusters)
    assert "guitar" not in rotulos


@pytest.mark.asyncio
async def test_um_ponto_por_faixa(analysis):
    r = await cluster_playlist(analysis)
    assert len(r.points) == len(analysis.tracks)
    assert {p[3] for p in r.points} == {c.id for c in r.clusters}


@pytest.mark.asyncio
async def test_playlist_curta_explica_em_vez_de_inventar(analysis):
    curta = PlaylistAnalysis(
        playlist=PlaylistSummary(id="p2", name="Curta", track_count=3),
        tracks=analysis.tracks[:3],
        genre_distribution=[],
        subgenre_distribution=[],
        top_artists=[],
        tracks_missing_genre=0,
        bpm_histogram=[],
    )
    r = await cluster_playlist(curta)

    assert r.clusters == []
    assert r.note is not None and str(MIN_FAIXAS) in r.note


@pytest.mark.asyncio
async def test_faixas_sem_tags_nao_quebram(analysis):
    for t in analysis.tracks:
        t.subgenre_tags = []
    r = await cluster_playlist(analysis)
    assert r.clusters == []
    assert r.note is not None


@pytest.mark.asyncio
async def test_playlist_homogenea_reporta_separacao_fraca(analysis, analysis_sobreposta):
    """Uma playlist sem blocos reais não pode ganhar blocos inventados.

    O k-means sempre devolve k grupos — a pergunta é se eles significam alguma
    coisa. A silhueta é o que responde isso, e o painel usa o valor para avisar
    que a divisão é fraca. Se ela não cair aqui, esse aviso nunca aparece.
    """
    clara = await cluster_playlist(analysis)
    turva = await cluster_playlist(analysis_sobreposta)

    assert turva.silhouette is not None
    assert turva.silhouette < clara.silhouette

    # E os grupos encontrados devem misturar os dois blocos de origem, porque
    # não há fronteira real entre eles.
    misturados = [
        c for c in turva.clusters
        if len({tid.split("-")[0] for tid in c.track_ids}) > 1
    ]
    assert misturados, "sem fronteira real, os grupos deveriam se misturar"
