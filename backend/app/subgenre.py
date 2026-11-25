"""Subgênero de uma faixa a partir de várias fontes de evidência.

Cada fonte (tags da faixa, tags do artista, andamento, e no futuro um modelo de
áudio) devolve uma distribuição sobre os subgêneros do gênero da faixa, ou se
abstém. `blend` soma as distribuições ponderadas pelo peso de cada fonte e diz
quanto confia no resultado: quando só o artista falou, quando o vencedor tem
pouca fatia ou quando as duas fontes mais pesadas discordam, o resultado vem
marcado `unsure` e não vira subgênero.

Tudo aqui é função pura — sem rede, sem banco. Uma fonte nova entra pelo
parâmetro `extra` de `blend`, sem mexer no resto.
"""
from typing import Iterable, NamedTuple

from . import taxonomy
from .models import EvidenceLine, SubgenreShare
from .taxonomy import Tag

# Quanto cada fonte pesa no blend (calibrados na Task 9).
SOURCE_WEIGHTS = {"track_tags": 1.0, "tempo": 0.8, "artist_tags": 0.4}
DEFAULT_SOURCE_WEIGHT = 0.6  # fonte extra sem peso próprio

# Um BPM fora da faixa de um subgênero perde verossimilhança linearmente e zera
# a esta distância dela.
TEMPO_FALLOFF_BPM = 6.0

# Abaixo desta fatia o vencedor não basta para virar subgênero.
UNSURE_MIN_SHARE = 0.5


class Evidence(NamedTuple):
    source: str
    says: str | None
    detail: str


class SourceResult(NamedTuple):
    name: str
    distribution: dict[str, float]  # soma 1
    evidence: list[Evidence]


class SubgenreResult(NamedTuple):
    blend: list[tuple[str, float]]
    lean: str | None
    subgenre: str | None
    confidence: float
    unsure: bool
    evidence: list[Evidence]


EMPTY_RESULT = SubgenreResult([], None, None, 0.0, False, [])


def _normalized(scores: dict[str, float]) -> dict[str, float]:
    total = sum(scores.values())
    return {k: v / total for k, v in scores.items()}


def _ranked(distribution: dict[str, float]) -> list[tuple[str, float]]:
    """Fatia decrescente, nome como desempate — determinístico."""
    return sorted(distribution.items(), key=lambda item: (-item[1], item[0]))


def _tied_top(distribution: dict[str, float]) -> list[str]:
    """Rótulos empatados no topo (≥ 0.999 da maior fatia), em ordem de nome."""
    ranked = _ranked(distribution)
    floor = ranked[0][1] * 0.999
    return [label for label, share in ranked if share >= floor]


def tags_source(name: str, genre: str, tags: list[Tag]) -> SourceResult | None:
    """Voto das tags que resolvem para um subgênero de `genre`.

    Tags que só casam com o gênero (sem subgênero) ou com outro gênero não
    votam. O alias fraco entra com peso reduzido (`tag_weight_factor`).
    """
    names = {i.name for i in taxonomy.subgenres_of(genre)}
    votes: list[tuple[str, Tag, float]] = []
    for tag in tags:
        node = taxonomy.resolve(tag.name)
        if node is None or node.genre != genre or node.subgenre not in names:
            continue
        votes.append((node.subgenre, tag, max(tag.weight, 0.0) * taxonomy.tag_weight_factor(tag.name)))
    if not votes:
        return None

    if sum(w for _, _, w in votes) <= 0:
        votes = [(sub, tag, 1.0) for sub, tag, _ in votes]  # sem peso: divide igual
    scores: dict[str, float] = {}
    for sub, _, weight in votes:
        scores[sub] = scores.get(sub, 0.0) + weight
    distribution = _normalized(scores)

    evidence = [
        Evidence(name, sub, f"tag '{tag.name}' aponta para {sub}")
        for sub, tag, _ in sorted(votes, key=lambda v: (-v[2], v[0], v[1].name.lower()))
    ]
    return SourceResult(name, distribution, evidence)


def _likelihoods(genre: str, bpm: float) -> dict[str, float]:
    out: dict[str, float] = {}
    for info in taxonomy.subgenres_of(genre):
        if info.bpm is None:
            continue
        low, high = info.bpm
        distance = max(low - bpm, bpm - high, 0.0)
        value = max(0.0, 1.0 - distance / TEMPO_FALLOFF_BPM)
        if value > 0:
            out[info.name] = value
    return out


def tempo_source(genre: str, bpm: float | None) -> SourceResult | None:
    """Voto do andamento: 1 dentro da faixa do subgênero, decaindo fora dela."""
    if bpm is None or bpm <= 0:
        return None

    likelihood = _likelihoods(genre, bpm)
    prefix = f"{bpm:g} BPM"
    if not likelihood:
        # Andamento lido pela metade (72 por 144) é comum em detecção de BPM.
        likelihood = _likelihoods(genre, bpm * 2)
        if not likelihood:
            return None
        prefix = f"{bpm:g} BPM lido como dobro ({bpm * 2:g})"

    distribution = _normalized(likelihood)
    tied = _tied_top(distribution)
    if len(tied) == 1:
        low, high = taxonomy.subgenre_info(tied[0]).bpm
        detail = f"{prefix}; {tied[0]} vai de {low:g} a {high:g}"
    else:
        detail = f"{prefix}; cabe em {', '.join(tied)}"
    return SourceResult("tempo", distribution, [Evidence("tempo", tied[0], detail)])


def blend(
    genre: str | None,
    *,
    artist_tags: list[Tag],
    track_tags: list[Tag],
    bpm: float | None = None,
    extra: Iterable[SourceResult] = (),
) -> SubgenreResult:
    """Combina as fontes num blend de subgêneros, com confiança e evidência."""
    if genre is None or not taxonomy.subgenres_of(genre):
        return EMPTY_RESULT

    candidates = [
        tags_source("track_tags", genre, track_tags),
        tempo_source(genre, bpm),
        tags_source("artist_tags", genre, artist_tags),
        *extra,
    ]
    sources = [s for s in candidates if s is not None]
    if not sources:
        return EMPTY_RESULT

    def weight(source: SourceResult) -> float:
        return SOURCE_WEIGHTS.get(source.name, DEFAULT_SOURCE_WEIGHT)

    mixed: dict[str, float] = {}
    for source in sources:
        for label, share in source.distribution.items():
            mixed[label] = mixed.get(label, 0.0) + weight(source) * share
    ranked = _ranked(_normalized(mixed))
    lean, confidence = ranked[0]

    heaviest = sorted(sources, key=weight, reverse=True)[:2]
    # Empate no topo conta como concordância: o andamento costuma caber em
    # vários subgêneros ao mesmo tempo.
    disagree = len(heaviest) == 2 and not (
        set(_tied_top(heaviest[0].distribution)) & set(_tied_top(heaviest[1].distribution))
    )
    unsure = (
        all(s.name == "artist_tags" for s in sources)
        or confidence < UNSURE_MIN_SHARE
        or disagree
    )

    return SubgenreResult(
        blend=ranked,
        lean=lean,
        subgenre=None if unsure else lean,
        confidence=confidence,
        unsure=unsure,
        evidence=[e for s in sources for e in s.evidence],
    )


def subgenre_fields(result: SubgenreResult) -> dict:
    """Os campos de subgênero de uma faixa (`TrackGenreInfo`/`TrackDetail`).

    Devolve modelos (não dicts) para servir tanto de kwargs quanto de
    `model_copy(update=...)`, que não valida. Não inclui `subgenre`, que quem
    classifica define à parte.
    """
    return {
        "subgenre_blend": [SubgenreShare(label=label, share=round(share, 3)) for label, share in result.blend],
        "subgenre_lean": result.lean,
        "subgenre_confidence": result.confidence or None,
        "subgenre_unsure": result.unsure,
        "subgenre_evidence": [EvidenceLine(source=e.source, says=e.says, detail=e.detail) for e in result.evidence],
    }
