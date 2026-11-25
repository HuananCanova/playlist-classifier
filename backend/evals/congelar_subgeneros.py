"""Congela as entradas do conjunto dourado de subgênero.

    cd backend
    .venv/Scripts/python.exe -m evals.congelar_subgeneros

Lê `subgenre_refs.yaml` (faixa + subgênero de referência externa), consulta o
Last.fm (tags da faixa e do artista, com peso) e o Deezer (BPM) e escreve
`subgenre_golden.yaml` com as entradas CONGELADAS: o runner roda offline e dá
sempre o mesmo número, e só este script — rodado de propósito — muda os dados.

Seguro para repetir: **não grava no banco do app** (os caches que escrevem em
`enrichment_store` viram no-op, como em `scripts/medir_fontes_psy.py`) e,
quando uma consulta falha (Last.fm sem resposta, Deezer fora do ar), reaproveita
o que o arquivo anterior já tinha para a faixa em vez de congelar "sem dados"
como se fosse resposta. Faixa que continua sem resposta ganha `incompleto: true`.
Os `limiares` do arquivo anterior são preservados.
"""
import asyncio
import sys
from pathlib import Path

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import deezer_client, enrichment_store, lastfm_client  # noqa: E402
from app.lastfm_client import NoAnswer  # noqa: E402

AQUI = Path(__file__).resolve().parent
REFS_PATH = AQUI / "subgenre_refs.yaml"
GOLDEN_PATH = AQUI / "subgenre_golden.yaml"
TENTATIVAS = 3
PAUSA_S = 1.5

# Os clientes leem e guardam no banco do app; o congelamento não pode tocar nele
# (nem ler: o que já estava lá não é "o que a API devolve agora").
for _nome in ("put_artist_tags", "put_track_tags", "put_deezer_match"):
    setattr(enrichment_store, _nome, lambda *a, **k: None)
for _nome in ("get_artist_tags", "get_track_tags", "get_deezer_match"):
    setattr(enrichment_store, _nome, lambda *a, **k: None)

CABECALHO = """\
# Conjunto dourado de subgênero — entradas CONGELADAS.
#
# Gerado por `python -m evals.congelar_subgeneros` a partir de `subgenre_refs.yaml`.
# NÃO edite os casos à mão: refaça o congelamento. Cada caso guarda o que o
# Last.fm (tags da faixa e do artista, com peso) e o Deezer (BPM) devolveram na
# data do congelamento, e o rótulo `subgenero` vem da referência externa
# registrada em `referencia` — nunca de julgamento nosso nem do classificador.
#
# Formato: id, faixa, referencia, subgenero, artista (tags do artista),
# faixa_tags (tags da faixa), bpm (null = Deezer sem BPM ou sem a faixa),
# incompleto (true = alguma fonte não respondeu no congelamento).
#
# `limiares` são os pisos/tetos que `run_subgenre_evals.py` cobra.

"""


def _tags(lista) -> list[list]:
    return [[t.name, round(t.weight)] for t in lista]


async def _com_tentativas(fabrica):
    """Repete até a fonte responder de verdade; devolve (resultado, respondeu)."""
    resultado = None
    for i in range(TENTATIVAS):
        if i:
            await asyncio.sleep(PAUSA_S * i)
        resultado = await fabrica()
        if not isinstance(resultado, (NoAnswer, deezer_client.Incomplete)):
            return resultado, True
    return resultado, False


async def congelar_caso(client: httpx.AsyncClient, ref: dict, antigo: dict | None) -> dict:
    artista, titulo = ref["artista"], ref["titulo"]
    credito = ref.get("credito") or artista
    caso = {
        "id": ref["id"],
        "faixa": f"{credito} — {titulo}",
        "referencia": ref["referencia"],
        "subgenero": ref["subgenero"],
    }
    incompleto = False

    tags_artista, ok = await _com_tentativas(lambda: lastfm_client.get_artist_tags(client, artista))
    if not ok and antigo is not None:
        caso["artista"] = antigo.get("artista") or []
    else:
        incompleto = incompleto or not ok
        caso["artista"] = _tags(tags_artista)

    tags_faixa, ok = await _com_tentativas(lambda: lastfm_client.get_track_tags(client, artista, titulo))
    if not ok and antigo is not None:
        caso["faixa_tags"] = antigo.get("faixa_tags") or []
    else:
        incompleto = incompleto or not ok
        caso["faixa_tags"] = _tags(tags_faixa)

    info, ok = await _com_tentativas(lambda: deezer_client.get_track_info(client, artista, titulo))
    if not ok and antigo is not None:
        caso["bpm"] = antigo.get("bpm")
    else:
        incompleto = incompleto or not ok
        caso["bpm"] = (info or {}).get("bpm")

    if incompleto or (not ok and antigo is not None and antigo.get("incompleto")):
        caso["incompleto"] = True
    return caso


async def main_async() -> int:
    refs = yaml.safe_load(REFS_PATH.read_text(encoding="utf-8"))["casos"]
    antigos: dict[str, dict] = {}
    limiares = {"precisao_confiante": 0.0, "max_incerto": 1.0}
    if GOLDEN_PATH.exists():
        anterior = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8")) or {}
        antigos = {c["id"]: c for c in anterior.get("casos") or []}
        limiares = anterior.get("limiares") or limiares

    casos = []
    async with httpx.AsyncClient() as client:
        for ref in refs:
            caso = await congelar_caso(client, ref, antigos.get(ref["id"]))
            casos.append(caso)
            print(
                f"{caso['id']:45} artista={len(caso['artista']):2d} faixa={len(caso['faixa_tags']):2d} "
                f"bpm={caso['bpm']}{'  INCOMPLETO' if caso.get('incompleto') else ''}"
            )

    corpo = yaml.safe_dump({"limiares": limiares, "casos": casos}, allow_unicode=True, sort_keys=False, width=110)
    GOLDEN_PATH.write_text(CABECALHO + corpo, encoding="utf-8")
    print(
        f"\n{len(casos)} casos: tags do artista {sum(1 for c in casos if c['artista'])}, "
        f"tags da faixa {sum(1 for c in casos if c['faixa_tags'])}, "
        f"BPM {sum(1 for c in casos if c['bpm'])}, "
        f"incompletos {sum(1 for c in casos if c.get('incompleto'))}"
    )
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
