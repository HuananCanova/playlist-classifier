"""Reclassifica gênero no que já está guardado, sem chamar ninguém.

Quando a taxonomia entrou (`app/taxonomy.py`), as análises e os resumos já no
banco continuaram com os rótulos antigos: cada tag de artista virava um gênero,
`hip-hop` e `hip hop` eram dois, e a lista saía em ordem alfabética. A página de
Perfil lê exatamente esses resumos, então a conta inteira continuaria mostrando
o gráfico velho até cada playlist ser analisada de novo.

Analisar de novo custaria uma varredura completa do Spotify — e a conta já foi
suspensa por 18 horas uma vez por volume de requisição. Mas não é preciso: as
tags estão guardadas dentro de cada análise e de cada resumo. Reclassificar é
reler o que está em disco e aplicar a taxonomia. **Zero chamadas externas.**

Uma diferença honesta em relação a uma análise nova: o que está guardado tem o
nome da tag, não o peso que o Last.fm deu a ela — o peso só passou a ser gravado
agora. Então aqui todas as tags da faixa valem igual, e o que decide é a
taxonomia (hierarquia, sinônimo e descarte), não a força relativa. Na prática
muda pouco, porque o pai é eleito pela soma dos filhos; quando a playlist for
analisada de novo, a classificação é refinada pelo peso sem nada a desfazer.

Por isso as tags da faixa e as do artista entram aqui num só balaio: separá-las
sugeriria uma precisão que o dado guardado não tem.
"""
import logging
from collections import Counter

from . import profile_store, taxonomy
from .models import GenreCount, PlaylistAnalysis, TrackGenreInfo

logger = logging.getLogger(__name__)

# O mesmo teto de `genre_analysis.MAX_DISPLAY_TAGS`, repetido aqui de propósito:
# importar de lá traria o módulo que fala com Spotify e Deezer para dentro de um
# script que não toca em rede.
MAX_DISPLAY_TAGS = 12

# O mesmo limite de `top_counts` em genre_analysis.
TOP_LIMIT = 25


def _balaio(*listas) -> list[str]:
    """As tags guardadas, sem repetir, em ordem alfabética.

    Alfabética, e não a ordem de chegada, porque o dado guardado não tem peso:
    sem peso, ordem nenhuma significa nada, e a ordem de chegada muda conforme
    o campo de onde a tag veio. Ordenar é o que faz o script ser idempotente —
    rodar duas vezes não reescreve a mesma faixa de outro jeito.

    Numa análise nova a ordem é por peso do Last.fm (`genre_analysis._display_tags`),
    que aí sim carrega informação: a primeira tag é a que mais descreve a faixa.
    """
    vistas: set[str] = set()
    saida: list[str] = []
    for lista in listas:
        for tag in lista or []:
            chave = (tag or "").strip().lower()
            if not chave or chave in vistas:
                continue
            vistas.add(chave)
            saida.append(tag)
    return sorted(saida, key=lambda t: t.strip().lower())


def track(faixa: TrackGenreInfo) -> TrackGenreInfo:
    """A faixa com gênero, subgênero, confiança e evidência da taxonomia."""
    tags = _balaio(faixa.genres, faixa.subgenre_tags)
    resultado = taxonomy.classify(artist_tags=tags)
    tabela = taxonomy.load()

    return faixa.model_copy(
        update={
            "genres": resultado.genres,
            # Tag que não é gênero sai; tag que a taxonomia ainda não conhece
            # fica, igual ao caminho novo (agrupamento e busca usam a palavra).
            "subgenre_tags": [t for t in tags if not tabela.discarded(t)][:MAX_DISPLAY_TAGS],
            "genre": resultado.genre,
            "subgenre": resultado.subgenre,
            "genre_confidence": resultado.confidence or None,
            "genre_evidence": resultado.evidence,
        }
    )


def current_version() -> int | None:
    """A versão da taxonomia em vigor."""
    return taxonomy.load().version


def is_current(guardado: PlaylistAnalysis | dict) -> bool:
    """Já classificado pela taxonomia em vigor?

    É o que torna o backfill idempotente — e a idempotência aqui PRECISA ser
    estrutural, não uma coincidência aritmética: o que está guardado contém os
    rótulos que o próprio backfill derivou, então reclassificar em cima deles
    muda a proporção dos votos e pode mover um gênero secundário para cima ou
    para baixo do piso de confiança. Medido no acervo real: a segunda passada
    reescrevia 239 das 2.228 faixas. Com o selo de versão, não reescreve
    nenhuma — e quando a taxonomia muda de versão, reescreve todas.
    """
    versao = guardado.genre_taxonomy if isinstance(guardado, PlaylistAnalysis) else guardado.get("genre_taxonomy")
    return versao is not None and versao == current_version()


def analysis(analise: PlaylistAnalysis) -> PlaylistAnalysis:
    """A análise com as faixas reclassificadas e as distribuições refeitas.

    As distribuições são recontadas do zero, com a mesma regra do caminho novo:
    um voto por faixa no gênero classificado, e um no subgênero quando existe.
    """
    faixas = [track(f) for f in analise.tracks]

    generos: Counter = Counter()
    subgeneros: Counter = Counter()
    sem_genero = 0
    for f in faixas:
        if f.genre is None:
            sem_genero += 1
            continue
        generos[f.genre] += 1
        if f.subgenre:
            subgeneros[f.subgenre] += 1

    def topo(contador: Counter) -> list[GenreCount]:
        return [GenreCount(label=r, count=n) for r, n in contador.most_common(TOP_LIMIT)]

    return analise.model_copy(
        update={
            "tracks": faixas,
            "genre_distribution": topo(generos),
            "subgenre_distribution": topo(subgeneros),
            "tracks_missing_genre": sem_genero,
            "genre_taxonomy": current_version(),
        }
    )


def digest(resumo: dict) -> tuple[dict, int]:
    """O resumo de perfil reclassificado, e quantas faixas mudaram de rótulo.

    O resumo guarda por faixa `genres` (os gêneros) e `tags` (as tags), que é o
    que `profile_stats` agrega. Depois disto, um resumo antigo fica indistinguível
    de um escrito pelo caminho novo — é essa a invariante que o teste cobra.
    """
    tabela = taxonomy.load()
    mudadas = 0
    faixas = []

    for f in resumo.get("tracks") or []:
        tags = _balaio(f.get("genres"), f.get("tags"))
        resultado = taxonomy.classify(artist_tags=tags)
        antes = list(f.get("genres") or [])
        nova = dict(f)
        nova["genres"] = resultado.genres
        # O mesmo teto do resumo escrito pelo caminho novo, para o resultado
        # ficar idêntico byte a byte no que importa.
        nova["tags"] = [
            t for t in tags if not tabela.discarded(t)
        ][: profile_store.MAX_TAGS_PER_TRACK]
        if nova["genres"] != antes:
            mudadas += 1
        faixas.append(nova)

    return {**resumo, "tracks": faixas, "genre_taxonomy": current_version()}, mudadas
