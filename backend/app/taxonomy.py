"""Classificação de gênero a partir das tags do Last.fm.

A camada que faltava entre "lista de tags" e "esta faixa é techno". Três etapas:

1. **Normalizar** — "Hip-Hop", "hip hop" e "hip_hop" são a mesma coisa; acento,
   pontuação e caixa saem do caminho antes de qualquer comparação.
2. **Resolver** — cada tag vira um nó da taxonomia (`taxonomy.yaml`), ou nada.
   "minimal techno" resolve para (techno, minimal techno); "brasil" não resolve
   para nada, porque não é gênero.
3. **Pontuar** — cada faixa distribui UM voto entre os gêneros que as suas tags
   resolveram, proporcional ao peso que o Last.fm dá a cada tag. O gênero com
   mais voto é o gênero da faixa, e a sobra vira confiança.

O que isso corrige, em relação a contar tags:

- Uma faixa com três artistas deixava até nove votos de gênero; agora deixa um.
- "rock" (422 faixas) liderava porque era contado JUNTO com "classic rock",
  "hard rock" e "indie rock". Agora o filho pontua o pai uma vez só.
- "hip-hop" (183) e "hip hop" (59) eram dois gêneros. Agora são um, com 242.
- `peso` do Last.fm (0–100) era descartado: "rock" com 100 e "chillwave" com 2
  valiam igual. Agora não.

Tudo aqui é função pura sobre tags — sem rede, sem banco, sem Spotify. É o que
permite medir a precisão num conjunto dourado (`evals/genre_golden.yaml`) e
rodar em CI.
"""
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Iterable, NamedTuple

import yaml

logger = logging.getLogger(__name__)

TAXONOMY_PATH = Path(__file__).resolve().parent / "taxonomy.yaml"

# As tags da faixa descrevem a faixa; as do artista descrevem a carreira dele.
# Quando as duas existem, a da faixa decide — mas a do artista não é descartada,
# porque no acervo real a maioria das faixas não tem tag própria no Last.fm
# (nesta conta: 45 de 45 vieram vazias na primeira passada).
TRACK_SHARE = 0.65
ARTIST_SHARE = 0.35

# Abaixo disto o gênero entrou por uma tag fraca e solta: fica fora da lista de
# gêneros da faixa, mas continua contando para a confiança do vencedor.
CONFIDENCE_FLOOR = 0.15

# Tags por faixa citadas como evidência da classificação.
MAX_EVIDENCE = 4

# Peso aplicado a um alias marcado `weak` no YAML: a tag resolve para o
# subgênero, mas vale pouco ("goa" sozinho costuma ser só o selo de época).
WEAK_FACTOR = 0.3


class Tag(NamedTuple):
    """Uma tag com o peso que o Last.fm dá a ela (0–100 na API)."""

    name: str
    weight: float = 100.0


class Node(NamedTuple):
    """Onde uma tag caiu na taxonomia. `subgenre` None = casou com o pai."""

    genre: str
    subgenre: str | None


class SubgenreInfo(NamedTuple):
    """Um subgênero com os dados de referência que o YAML guarda sobre ele."""

    genre: str
    name: str
    bpm: tuple[float, float] | None
    about: str | None
    source: str | None


class Classification(NamedTuple):
    genre: str | None
    subgenre: str | None
    # 0–1: fração do voto da faixa que foi para o gênero vencedor. 1.0 = todas as
    # tags que resolveram apontam para o mesmo gênero.
    confidence: float
    # Os gêneros acima do piso, em ordem de voto — o que vai para `genres`.
    genres: list[str]
    # As tags originais que elegeram o vencedor, para a interface poder explicar.
    evidence: list[str]
    # Tags que não encontraram casa na taxonomia. Alimentam o relatório de
    # cobertura: é a fila de trabalho para estender o YAML.
    unresolved: list[str]


EMPTY = Classification(None, None, 0.0, [], [], [])


def normalize(text: str) -> str:
    """Forma comparável de uma tag: sem acento, sem pontuação, minúscula.

    "Hip-Hop" e "hip hop" viram "hip hop"; "Forró" vira "forro"; "R&B" vira
    "r b". Aliases do YAML passam pela mesma função, então basta escrever uma
    grafia por ideia.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    collapsed = re.sub(r"[^a-z0-9]+", " ", ascii_only.lower())
    return collapsed.strip()


class _Taxonomy:
    """O YAML, indexado para consulta em tempo constante."""

    def __init__(self, data: dict):
        self.version = data.get("version")
        self.index: dict[str, Node] = {}
        self.ignored: set[str] = set()
        self.patterns: list[re.Pattern] = []
        # Gêneros marcados `fallback` no YAML: supergêneros cuja tag SOLTA só
        # vale quando nada mais classificou a faixa (ver `classify`).
        self.fallbacks: set[str] = set()
        # Aliases fracos (chave normalizada) e dados de referência dos subgêneros.
        self.weak: set[str] = set()
        self.subgenre_infos: dict[str, SubgenreInfo] = {}

        ignore = data.get("ignore") or {}
        for key, values in ignore.items():
            if key == "patterns":
                self.patterns = [re.compile(p) for p in (values or [])]
                continue
            for raw in values or []:
                self.ignored.add(normalize(raw))

        for genre, body in (data.get("genres") or {}).items():
            body = body or {}
            if body.get("fallback"):
                self.fallbacks.add(genre)
            self._put(genre, Node(genre, None))
            for alias in body.get("aliases") or []:
                self._put(alias, Node(genre, None))
            for subgenre, spec in (body.get("subgenres") or {}).items():
                # Duas formas: a lista de aliases (antiga) ou um mapeamento com
                # aliases, weak, bpm, about e source.
                if isinstance(spec, dict):
                    aliases = spec.get("aliases") or []
                    weak = spec.get("weak") or []
                    bpm = spec.get("bpm")
                else:
                    aliases, weak, bpm, spec = spec or [], [], None, {}
                self._put(subgenre, Node(genre, subgenre))
                for alias in aliases:
                    self._put(alias, Node(genre, subgenre))
                for alias in weak:
                    self._put(alias, Node(genre, subgenre))
                    self.weak.add(normalize(alias))
                self.subgenre_infos[normalize(subgenre)] = SubgenreInfo(
                    genre=genre,
                    name=subgenre,
                    bpm=(float(bpm[0]), float(bpm[1])) if bpm else None,
                    about=spec.get("about"),
                    source=spec.get("source"),
                )

        self.genres: list[str] = list((data.get("genres") or {}).keys())

    def _put(self, raw: str, node: Node) -> None:
        key = normalize(raw)
        if not key:
            return
        existing = self.index.get(key)
        if existing is not None and existing != node:
            # Duas entradas reivindicando a mesma grafia é erro de edição do
            # YAML, não um caso a resolver em tempo de execução: a primeira
            # vence e o aviso aponta onde arrumar.
            logger.warning(
                "taxonomy.yaml: %r já aponta para %s; ignorando %s", raw, existing, node
            )
            return
        self.index[key] = node

    def discarded(self, tag: str) -> bool:
        """True quando a tag foi descartada de propósito (ignore ou padrão).

        Separado de "não resolveu" porque só o segundo caso é trabalho pendente:
        o relatório de cobertura lista o que falta no YAML, não o que o YAML já
        decidiu jogar fora.
        """
        key = normalize(tag)
        if not key or key in self.ignored:
            return True
        return any(p.search(key) for p in self.patterns)

    def resolve(self, tag: str) -> Node | None:
        if self.discarded(tag):
            return None
        return self.index.get(normalize(tag))


@lru_cache(maxsize=1)
def load() -> _Taxonomy:
    data = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))
    taxonomy = _Taxonomy(data)
    logger.info(
        "Taxonomia v%s: %d gêneros, %d entradas, %d descartes",
        taxonomy.version, len(taxonomy.genres), len(taxonomy.index), len(taxonomy.ignored),
    )
    return taxonomy


def resolve(tag: str) -> Node | None:
    """O nó de uma tag, ou None se ela não é gênero (ou é desconhecida)."""
    return load().resolve(tag)


def subgenre_info(name: str) -> SubgenreInfo | None:
    """Os dados de referência de um subgênero (pelo nome canônico), ou None."""
    return load().subgenre_infos.get(normalize(name))


def subgenres_of(genre: str) -> list[SubgenreInfo]:
    """Os subgêneros de um gênero, na ordem do YAML."""
    return [i for i in load().subgenre_infos.values() if i.genre == genre]


def tag_weight_factor(tag: str) -> float:
    """`WEAK_FACTOR` para um alias marcado `weak` no YAML; 1.0 para o resto."""
    return WEAK_FACTOR if normalize(tag) in load().weak else 1.0


def as_tags(tags: Iterable[Tag | tuple[str, float] | str]) -> list[Tag]:
    """Aceita Tag, (nome, peso) ou só o nome — tags antigas do banco são strings."""
    out: list[Tag] = []
    for item in tags or []:
        if isinstance(item, Tag):
            out.append(item)
        elif isinstance(item, str):
            out.append(Tag(item))
        elif isinstance(item, (tuple, list)) and item:
            name = item[0]
            weight = float(item[1]) if len(item) > 1 and item[1] is not None else 100.0
            out.append(Tag(str(name), weight))
    return out


def _votes(tags: list[Tag], share: float) -> tuple[dict[Node, float], dict[Node, list[Tag]], list[str]]:
    """Distribui `share` de voto entre os nós que as tags resolveram.

    Normalizar dentro da fonte é o que torna artista e faixa comparáveis: uma
    faixa com oito tags não pesa oito vezes mais que uma com duas.
    """
    resolved: list[tuple[Node, Tag]] = []
    unresolved: list[str] = []
    taxonomy = load()

    for tag in tags:
        node = taxonomy.resolve(tag.name)
        if node is None:
            if not taxonomy.discarded(tag.name):
                unresolved.append(tag.name)
            continue
        resolved.append((node, tag))

    # Alias fraco entra no voto com peso reduzido, antes de normalizar.
    def weight(tag: Tag) -> float:
        return max(tag.weight, 0.0) * tag_weight_factor(tag.name)

    total = sum(weight(t) for _, t in resolved)
    scores: dict[Node, float] = {}
    sources: dict[Node, list[Tag]] = {}
    if total <= 0:
        # Pesos ausentes ou todos zero: divide igual entre o que resolveu.
        for node, tag in resolved:
            scores[node] = scores.get(node, 0.0) + share / len(resolved)
            sources.setdefault(node, []).append(tag)
        return scores, sources, unresolved

    for node, tag in resolved:
        scores[node] = scores.get(node, 0.0) + share * weight(tag) / total
        sources.setdefault(node, []).append(tag)
    return scores, sources, unresolved


def classify(
    artist_tags: Iterable[Tag | tuple[str, float] | str] = (),
    track_tags: Iterable[Tag | tuple[str, float] | str] = (),
) -> Classification:
    """O gênero de uma faixa, com subgênero, confiança e evidência."""
    artist = as_tags(artist_tags)
    track = as_tags(track_tags)

    # Quando um dos lados não resolveu nada, o outro leva o voto inteiro — senão
    # uma faixa sem tag própria (a maioria) sairia com confiança artificialmente
    # baixa só por isso.
    artist_scores, artist_sources, artist_open = _votes(artist, 1.0)
    track_scores, track_sources, track_open = _votes(track, 1.0)
    if artist_scores and track_scores:
        artist_scores = {k: v * ARTIST_SHARE for k, v in artist_scores.items()}
        track_scores = {k: v * TRACK_SHARE for k, v in track_scores.items()}

    scores: dict[Node, float] = dict(artist_scores)
    for node, value in track_scores.items():
        scores[node] = scores.get(node, 0.0) + value
    sources: dict[Node, list[Tag]] = {k: list(v) for k, v in artist_sources.items()}
    for node, tags in track_sources.items():
        sources.setdefault(node, []).extend(tags)

    if not scores:
        return Classification(None, None, 0.0, [], [], sorted(set(artist_open + track_open)))

    # Supergênero de carona sai da conta. "electronic" e "trance" aparecem como
    # tag solta em quase toda faixa de techno, house ou psytrance, e contá-los
    # inflava um rótulo que não diz o que a faixa é — no perfil desta conta,
    # "electronic" chegava ao segundo lugar desse jeito. A tag solta de um
    # gênero `fallback` só vale quando nada mais classificou a faixa; o subgênero
    # dele (dubstep, ambient, progressive trance) pontua sempre, porque esse diz.
    taxonomia = load()
    de_carona = {
        node for node in scores
        if node.subgenre is None and node.genre in taxonomia.fallbacks
    }
    if de_carona and len(de_carona) < len(scores):
        for node in de_carona:
            del scores[node]
            sources.pop(node, None)

    # O filho pontua o pai: é o que faz "minimal techno" ser techno.
    genre_scores: dict[str, float] = {}
    for node, value in scores.items():
        genre_scores[node.genre] = genre_scores.get(node.genre, 0.0) + value

    total = sum(genre_scores.values()) or 1.0

    def genre_rank(genre: str) -> tuple:
        # Empate resolvido por: mais voto, mais tags distintas, ordem alfabética.
        # Determinístico de propósito — o conjunto dourado depende disso.
        votes = sum(1 for node in scores if node.genre == genre)
        return (-genre_scores[genre], -votes, genre)

    ordered = sorted(genre_scores, key=genre_rank)
    winner = ordered[0]
    confidence = genre_scores[winner] / total

    subgenre_scores = {
        node.subgenre: value
        for node, value in scores.items()
        if node.genre == winner and node.subgenre is not None
    }
    subgenre = None
    if subgenre_scores:
        subgenre = sorted(subgenre_scores, key=lambda s: (-subgenre_scores[s], s))[0]

    evidence = [
        tag.name
        for tag in sorted(
            (t for node, tags in sources.items() if node.genre == winner for t in tags),
            # Caixa fora do critério: "Psytrance" e "psytrance" são a mesma tag,
            # e ordenar por ASCII poria toda tag capitalizada na frente.
            key=lambda t: (-t.weight, t.name.lower()),
        )
    ]
    # Sem repetir a mesma tag duas vezes (artista e faixa podem trazer a mesma).
    seen: set[str] = set()
    unique_evidence = [t for t in evidence if not (t.lower() in seen or seen.add(t.lower()))]

    genres = [g for g in ordered if genre_scores[g] / total >= CONFIDENCE_FLOOR]

    return Classification(
        genre=winner,
        subgenre=subgenre,
        confidence=round(confidence, 3),
        genres=genres,
        evidence=unique_evidence[:MAX_EVIDENCE],
        unresolved=sorted(set(artist_open + track_open)),
    )
