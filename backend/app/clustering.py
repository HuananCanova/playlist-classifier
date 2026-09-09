"""Agrupa as faixas de uma playlist em climas, com k-means sobre as tags.

A distribuição de gêneros responde "do que essa playlist é feita" — 34% indie
rock, 21% dream pop. O que ela não mostra é que essas fatias podem ser blocos
separados: uma playlist de 60 faixas costuma ser duas ou três playlists
convivendo, e a contagem global achata isso numa média que não descreve
nenhuma delas.

Aqui as faixas viram vetores TF-IDF das suas tags, e o k-means separa os
blocos. O rótulo de cada grupo sai das tags que mais o distinguem do resto da
playlist — não das mais frequentes nele. `guitar` pode ser a tag mais comum de
um grupo e ainda assim ser inútil como nome, se for a mais comum de todos.

Sobre o que NÃO entra nas features:

- **BPM.** Seria o sinal numérico mais interessante, mas só existe via Deezer,
  uma chamada por faixa. Numa playlist de 100 faixas isso é caro demais para
  um painel que carrega junto com a página.
- **As features espectrais do `audioAnalysis.js`.** São calculadas no navegador
  a partir da prévia de 30s, e só para a faixa que está tocando.

Sobra o que a análise já tem em mãos: tags, duração e popularidade.
"""
import asyncio
import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Abaixo disso não há o que agrupar: k-means em 7 pontos devolve ruído com
# aparência de estrutura.
MIN_FAIXAS = 12

# Teto de grupos. Mais que isso vira uma lista de faixas com passos extras.
MAX_K = 6

# Quantas tags nomeiam um grupo.
TAGS_POR_GRUPO = 4


@dataclass(frozen=True)
class Cluster:
    id: int
    label: str
    size: int
    top_tags: list[str]
    track_ids: list[str]
    sample_tracks: list[str]


@dataclass(frozen=True)
class ClusterResult:
    clusters: list[Cluster]
    k: int
    silhouette: float | None
    # Projeção 2D das faixas, para o gráfico: (track_id, x, y, cluster_id).
    points: list[tuple[str, float, float, int]]
    note: str | None = None


def _empty(note: str) -> ClusterResult:
    return ClusterResult(clusters=[], k=0, silhouette=None, points=[], note=note)


def _cluster_sync(
    track_ids: list[str],
    nomes: list[str],
    documentos: list[str],
    numericos: list[tuple[float, float]],
) -> ClusterResult:
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    # `min_df=2`: uma tag que aparece numa faixa só não separa nada e ainda
    # empurra aquela faixa para um grupo particular.
    vectorizer = TfidfVectorizer(
        analyzer=lambda doc: doc.split(" | "),
        min_df=2,
        sublinear_tf=True,
    )
    try:
        tfidf = vectorizer.fit_transform(documentos)
    except ValueError:
        return _empty("As faixas não têm tags em comum suficientes para agrupar.")

    if tfidf.shape[1] < 2:
        return _empty("Poucas tags distintas nesta playlist para separar grupos.")

    # SVD antes do k-means: distância euclidiana em espaço esparso de centenas
    # de dimensões perde sentido, e o k-means só sabe medir assim.
    componentes = min(30, tfidf.shape[1] - 1, len(track_ids) - 1)
    denso = TruncatedSVD(n_components=componentes, random_state=0).fit_transform(tfidf)

    # Duração e popularidade entram padronizadas e com peso menor: são um
    # tempero, não devem dominar as tags.
    extras = StandardScaler().fit_transform(np.array(numericos, dtype=float)) * 0.35
    features = np.hstack([denso, extras])

    melhor: tuple[float, int, "np.ndarray"] | None = None
    for k in range(2, min(MAX_K, len(track_ids) - 1) + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(features)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(features, labels)
        if melhor is None or score > melhor[0]:
            melhor = (score, k, labels)

    if melhor is None:
        return _empty("Não foi possível separar grupos nesta playlist.")

    silhueta, k, labels = melhor

    # Rótulo por distinção, não por frequência: a média TF-IDF da tag dentro do
    # grupo menos a média dela na playlist inteira.
    termos = np.array(vectorizer.get_feature_names_out())
    tfidf_denso = tfidf.toarray()
    media_geral = tfidf_denso.mean(axis=0)

    clusters: list[Cluster] = []
    for cid in range(k):
        mask = labels == cid
        indices = [i for i, m in enumerate(mask) if m]
        if not indices:
            continue

        distincao = tfidf_denso[mask].mean(axis=0) - media_geral
        top = termos[np.argsort(distincao)[::-1][:TAGS_POR_GRUPO]].tolist()

        clusters.append(
            Cluster(
                id=cid,
                label=" · ".join(top[:2]) if top else f"Grupo {cid + 1}",
                size=len(indices),
                top_tags=top,
                track_ids=[track_ids[i] for i in indices],
                sample_tracks=[nomes[i] for i in indices[:5]],
            )
        )

    # Duas dimensões só para desenhar. É uma sombra do espaço real: pontos
    # próximos no gráfico costumam estar próximos de verdade, mas a distância
    # exata na tela não significa nada.
    plano = TruncatedSVD(n_components=2, random_state=0).fit_transform(tfidf)
    points = [
        (track_ids[i], round(float(plano[i][0]), 4), round(float(plano[i][1]), 4), int(labels[i]))
        for i in range(len(track_ids))
    ]

    clusters.sort(key=lambda c: c.size, reverse=True)
    return ClusterResult(
        clusters=clusters,
        k=k,
        silhouette=None if math.isnan(silhueta) else round(float(silhueta), 4),
        points=points,
    )


async def cluster_playlist(analysis) -> ClusterResult:
    """Agrupa as faixas de uma `PlaylistAnalysis` já pronta.

    Não faz nenhuma chamada externa: trabalha só sobre o que a análise trouxe.
    """
    com_tags = [t for t in analysis.tracks if t.subgenre_tags]
    if len(com_tags) < MIN_FAIXAS:
        return _empty(
            f"São necessárias ao menos {MIN_FAIXAS} faixas com tags para agrupar; "
            f"esta playlist tem {len(com_tags)}."
        )

    track_ids = [t.track_id for t in com_tags]
    nomes = [t.name for t in com_tags]
    # O TfidfVectorizer recebe as tags já tokenizadas, separadas por " | ":
    # tags são multipalavra ("dream pop") e quebrar por espaço as destruiria.
    documentos = [" | ".join(sorted({g.strip().lower() for g in t.subgenre_tags})) for t in com_tags]
    numericos = [(float(t.duration_ms or 0), float(t.popularity or 0)) for t in com_tags]

    # scikit-learn é síncrono e usa CPU; fora do loop para não travar o servidor.
    return await asyncio.to_thread(_cluster_sync, track_ids, nomes, documentos, numericos)
