"""O selo (gravadora) do lançamento como evidência de subgênero.

No psytrance o selo é uma pista forte e por lançamento — um disco da Suntrip é
goa, um da Parvati é forest — e é a fonte com mais cobertura que temos: medido
no conjunto dourado, 77% das faixas têm selo, contra 26% com BPM e 0% com tag
de faixa.

O mapa vive em `labels.yaml`, escrito à mão a partir das listas "Notable
labels" de https://psytranceguide.com/ (a mesma referência que a taxonomia já
cita para as faixas de BPM), e **não** a partir do conjunto dourado — que só
mede. Selo fora do mapa se abstém: não vota nem conta como incerteza.

Como o resto de `subgenre.py`, aqui não há rede nem banco. Quem busca o selo no
Deezer passa o nome pronto.
"""
import logging
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import yaml

from . import taxonomy
from .subgenre import Evidence, SourceResult, _normalized

logger = logging.getLogger(__name__)

LABELS_PATH = Path(__file__).resolve().parent / "labels.yaml"


class LabelInfo(NamedTuple):
    name: str
    shares: dict[str, float]
    nota: str
    fonte: str
    estilos: list[str]


def normalize(name: str) -> str:
    """Forma comparável de um nome de selo.

    O Deezer escreve o mesmo selo de formas diferentes ("MAGIC MOMENTS
    RECORDS", "Spin Twist Records", "Twisted Records Ltd"), então caixa, acento
    e pontuação saem antes de comparar. O resto do nome fica: tirar "records"
    juntaria selos distintos ("Twisted Records" e "Twisted"), e é o tipo de
    atalho que transforma evidência em palpite.
    """
    decomposed = unicodedata.normalize("NFKD", name or "")
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    out = []
    for char in ascii_only.lower():
        out.append(char if char.isalnum() else " ")
    return " ".join("".join(out).split())


class _Map:
    def __init__(self, data: dict):
        self.version = data.get("version")
        self.default_source = data.get("fonte_padrao") or ""
        self.by_name: dict[str, LabelInfo] = {}

        for name, body in (data.get("selos") or {}).items():
            body = body or {}
            shares = {k: float(v) for k, v in (body.get("shares") or {}).items() if float(v) > 0}
            if not shares:
                logger.warning("labels.yaml: %r sem shares; ignorado", name)
                continue
            info = LabelInfo(
                name=name,
                shares=_normalized(shares),
                nota=body.get("nota") or "",
                fonte=body.get("fonte") or self.default_source,
                estilos=list(body.get("estilos") or []),
            )
            for spelling in [name, *(body.get("aliases") or [])]:
                key = normalize(spelling)
                if not key:
                    continue
                existing = self.by_name.get(key)
                if existing is not None and existing.name != name:
                    logger.warning(
                        "labels.yaml: %r já aponta para %s; ignorando %s", spelling, existing.name, name
                    )
                    continue
                self.by_name[key] = info

    def lookup(self, label: str | None) -> LabelInfo | None:
        return self.by_name.get(normalize(label or "")) if label else None


@lru_cache(maxsize=1)
def load() -> _Map:
    data = yaml.safe_load(LABELS_PATH.read_text(encoding="utf-8"))
    mapa = _Map(data)
    logger.info("Mapa de selos v%s: %d grafias", mapa.version, len(mapa.by_name))
    return mapa


def lookup(label: str | None) -> LabelInfo | None:
    """O que sabemos deste selo, ou None quando ele não está no mapa."""
    return load().lookup(label)


def label_source(genre: str | None, label: str | None) -> SourceResult | None:
    """Voto do selo, ou None quando ele se abstém.

    Abstém-se quando: não há selo, o selo não está no mapa, ou nenhuma das
    fatias dele é subgênero DESTE gênero — um selo de psy não tem o que dizer
    sobre uma faixa de rock.
    """
    info = lookup(label)
    if info is None or genre is None:
        return None

    nomes = {i.name for i in taxonomy.subgenres_of(genre)}
    shares = {sub: share for sub, share in info.shares.items() if sub in nomes}
    if not shares:
        return None

    distribution = _normalized(shares)
    ranked = sorted(distribution.items(), key=lambda item: (-item[1], item[0]))
    says = ranked[0][0] if len(ranked) == 1 else None
    if len(ranked) > 1:
        reparte = ", ".join(f"{sub} {share:.0%}" for sub, share in ranked)
        detail = f"selo {info.name} reparte entre {reparte}"
    else:
        detail = f"selo {info.name} lança {ranked[0][0]}"
    if info.nota:
        detail = f"{detail} — {info.nota.rstrip('.')}"

    return SourceResult("label", distribution, [Evidence("label", says, detail)])
