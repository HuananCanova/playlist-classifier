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

Exceção: a evidência por faixa (`evidence_store`) guarda as tags do artista e as
da faixa separadas e com peso, mais o BPM. Onde ela existe, o gênero e o blend de
subgêneros saem dela. Onde não existe, o balaio vira "tags do artista" no blend:
fonte só de artista nunca decide sozinha, então a faixa fica honestamente incerta
até o andamento ou as tags da faixa chegarem.
"""
import json
import logging
import time
from collections import Counter

from . import analysis_store, db, evidence_store, profile_store, subgenre, taxonomy
from .evidence_store import TrackEvidence
from .models import GenreCount, PlaylistAnalysis, TrackGenreInfo
from .taxonomy import Tag

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


def _classify(
    balaio: list[str], evidencia: TrackEvidence | None
) -> tuple[taxonomy.Classification, list[Tag], list[Tag]]:
    """Gênero e as tags que alimentam o blend: da evidência quando ela tem tags, senão do balaio."""
    if _tem_tags(evidencia):
        artista, faixa = evidencia.artist_tags or [], evidencia.track_tags or []
        return taxonomy.classify(artist_tags=artista, track_tags=faixa), artista, faixa
    return taxonomy.classify(artist_tags=balaio), taxonomy.as_tags(balaio), []


def _tem_tags(evidencia: TrackEvidence | None) -> bool:
    return evidencia is not None and (evidencia.artist_tags is not None or evidencia.track_tags is not None)


def _tags_da_faixa(guardadas: list[str], evidencia: TrackEvidence | None) -> list[str]:
    """As tags de exibição: as da evidência quando existe (não dependem do que uma
    passada anterior escreveu), senão o balaio do guardado."""
    if _tem_tags(evidencia):
        return _balaio([t.name for t in (evidencia.artist_tags or []) + (evidencia.track_tags or [])])
    return guardadas


def _blend(genero, artista, faixa, evidencia, bpm_guardado):
    bpm = evidencia.bpm if evidencia is not None and evidencia.bpm is not None else bpm_guardado
    return subgenre.blend(genero, artist_tags=artista, track_tags=faixa, bpm=bpm)


def track(faixa: TrackGenreInfo, evidence: TrackEvidence | None = None) -> TrackGenreInfo:
    """A faixa com gênero, subgênero, confiança e evidência da taxonomia."""
    tags = _tags_da_faixa(_balaio(faixa.genres, faixa.subgenre_tags), evidence)
    resultado, artista, da_faixa = _classify(tags, evidence)
    mistura = _blend(resultado.genre, artista, da_faixa, evidence, faixa.bpm)
    tabela = taxonomy.load()

    return faixa.model_copy(
        update={
            "genres": resultado.genres,
            # Tag que não é gênero sai; tag que a taxonomia ainda não conhece
            # fica, igual ao caminho novo (agrupamento e busca usam a palavra).
            "subgenre_tags": [t for t in tags if not tabela.discarded(t)][:MAX_DISPLAY_TAGS],
            "genre": resultado.genre,
            "subgenre": mistura.subgenre,
            "genre_confidence": resultado.confidence or None,
            "genre_evidence": resultado.evidence,
            **subgenre.subgenre_fields(mistura),
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
    if isinstance(guardado, PlaylistAnalysis):
        versao = guardado.genre_taxonomy
        # Campo ausente no JSON guardado = análise de antes do blend de subgêneros.
        tem_subgenero = "subgenre_bars" in guardado.model_fields_set
    else:
        versao = guardado.get("genre_taxonomy")
        tem_subgenero = all("subgenre_blend" in f for f in guardado.get("tracks") or [])
    return versao is not None and versao == current_version() and tem_subgenero


def analysis(analise: PlaylistAnalysis, only_evidence: bool = False) -> PlaylistAnalysis:
    """A análise com as faixas reclassificadas e as distribuições refeitas.

    As distribuições são recontadas do zero, com a mesma regra do caminho novo:
    um voto por faixa no gênero classificado, um no subgênero para onde ela
    pende, e as fatias do blend somadas nas barras (seguras ou incertas).

    Com `only_evidence`, só as faixas com evidência guardada são refeitas; as
    outras ficam exatamente como estão (reclassificar o que já foi reclassificado
    reembaralha as faixas sem evidência), e só as distribuições são recontadas.
    """
    evidencias = evidence_store.get_many([f.track_id for f in analise.tracks])
    faixas = [
        f if only_evidence and f.track_id not in evidencias else track(f, evidencias.get(f.track_id))
        for f in analise.tracks
    ]

    generos: Counter = Counter()
    subgeneros: Counter = Counter()
    barras: dict[str, list[float]] = {}
    sem_genero = 0
    for f in faixas:
        if f.genre is None:
            sem_genero += 1
        else:
            generos[f.genre] += 1
        if f.subgenre_lean:
            subgeneros[f.subgenre_lean] += 1
        subgenre.add_to_bars(barras, [(b.label, b.share) for b in f.subgenre_blend], f.subgenre_unsure)

    def topo(contador: Counter) -> list[GenreCount]:
        return [GenreCount(label=r, count=n) for r, n in contador.most_common(TOP_LIMIT)]

    return analise.model_copy(
        update={
            "tracks": faixas,
            "genre_distribution": topo(generos),
            "subgenre_distribution": topo(subgeneros),
            "subgenre_bars": subgenre.bars_from(barras),
            "tracks_missing_genre": sem_genero,
            "genre_taxonomy": current_version(),
        }
    )


def digest(resumo: dict, only_evidence: bool = False) -> tuple[dict, int]:
    """O resumo de perfil reclassificado, e quantas faixas mudaram de rótulo.

    O resumo guarda por faixa `genres` (os gêneros) e `tags` (as tags), que é o
    que `profile_stats` agrega, mais `subgenre_lean/unsure/blend`. Depois disto,
    um resumo antigo fica indistinguível de um escrito pelo caminho novo — é essa
    a invariante que o teste cobra. O resumo não guarda as tags separadas, então
    sem evidência o balaio entra no blend como tags de artista.
    """
    tabela = taxonomy.load()
    evidencias = evidence_store.get_many([f["id"] for f in resumo.get("tracks") or [] if f.get("id")])
    mudadas = 0
    faixas = []

    for f in resumo.get("tracks") or []:
        if only_evidence and f.get("id") not in evidencias:
            faixas.append(f)
            continue
        tags = _tags_da_faixa(_balaio(f.get("genres"), f.get("tags")), evidencias.get(f.get("id")))
        resultado, artista, da_faixa = _classify(tags, evidencias.get(f.get("id")))
        mistura = _blend(resultado.genre, artista, da_faixa, evidencias.get(f.get("id")), f.get("bpm"))
        campos = subgenre.subgenre_fields(mistura)
        antes = list(f.get("genres") or [])
        nova = dict(f)
        nova["genres"] = resultado.genres
        # O mesmo teto do resumo escrito pelo caminho novo, para o resultado
        # ficar idêntico byte a byte no que importa.
        nova["tags"] = [
            t for t in tags if not tabela.discarded(t)
        ][: profile_store.MAX_TAGS_PER_TRACK]
        nova["subgenre_lean"] = campos["subgenre_lean"]
        nova["subgenre_unsure"] = campos["subgenre_unsure"]
        nova["subgenre_blend"] = [[b.label, round(b.share, 3)] for b in campos["subgenre_blend"]]
        if nova["genres"] != antes:
            mudadas += 1
        faixas.append(nova)

    return {**resumo, "tracks": faixas, "genre_taxonomy": current_version()}, mudadas


def account(playlist_ids: list[str]) -> dict:
    """Reclassifica as análises e os resumos guardados destas playlists.

    Chamada depois de buscar evidência nova: reescreve sempre (não pula o que já
    está na versão atual), porque o que mudou foi a evidência, não a taxonomia.
    Linha que já está atual só tem refeitas as faixas com evidência guardada; as
    demais não são tocadas (o que está guardado nelas foi derivado do próprio
    balaio, e reclassificar de novo o mudaria). Linha antiga leva a passada
    completa. Devolve quantas linhas reescreveu.
    """
    agora = time.time()
    contagem = {"analyses": 0, "digests": 0}
    for playlist_id in dict.fromkeys(playlist_ids):
        linha = db.query_one(
            "SELECT analysis FROM playlist_analyses WHERE playlist_id = ? AND format = ?",
            (playlist_id, analysis_store.ANALYSIS_FORMAT),
        )
        if linha is not None:
            try:
                guardada = PlaylistAnalysis.model_validate_json(linha["analysis"])
                nova = analysis(guardada, only_evidence=is_current(guardada))
            except ValueError:
                logger.warning("Análise ilegível em %s, pulando", playlist_id)
            else:
                db.execute(
                    "UPDATE playlist_analyses SET analysis = ?, saved_at = ? WHERE playlist_id = ?",
                    (nova.model_dump_json(), agora, playlist_id),
                )
                contagem["analyses"] += 1

        linha = db.query_one(
            "SELECT digest FROM playlist_digests WHERE playlist_id = ? AND format = ?",
            (playlist_id, profile_store.VERSION),
        )
        if linha is not None:
            try:
                guardado = json.loads(linha["digest"])
                resumo, _ = digest(guardado, only_evidence=is_current(guardado))
            except (ValueError, TypeError):
                logger.warning("Resumo ilegível em %s, pulando", playlist_id)
            else:
                resumo["saved_at"] = agora
                db.execute(
                    "UPDATE playlist_digests SET digest = ?, saved_at = ? WHERE playlist_id = ?",
                    (db.dumps(resumo), agora, playlist_id),
                )
                contagem["digests"] += 1

    profile_store.clear_memo()
    return contagem
