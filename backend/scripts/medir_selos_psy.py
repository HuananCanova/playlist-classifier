"""Mede o quanto o selo (gravadora) do Deezer ajuda a separar o psytrance.

    cd backend
    python -m scripts.medir_selos_psy [--faixas 150]     # biblioteca guardada
    python -m scripts.medir_selos_psy --golden           # conjunto dourado

Na biblioteca: quantas faixas psy têm selo no Deezer e quais selos aparecem
mais (se poucos selos cobrem muitas faixas, um mapa feito à mão vale a pena).
No conjunto dourado: cruza o selo com o subgênero da referência externa, para
ver se o selo aponta o subgênero certo. **Não grava nada no banco.**
"""
import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
import yaml  # noqa: E402

from app import deezer_client, enrichment_store  # noqa: E402

GOLDEN = Path(__file__).resolve().parent.parent / "evals" / "subgenre_golden.yaml"
CONCORRENCIA = 4


def faixas_do_golden() -> list[dict]:
    casos = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["casos"]
    faixas = []
    for caso in casos:
        artista, _, nome = caso["faixa"].partition(" — ")
        faixas.append({"artista": artista.strip(), "nome": nome.strip(), "subgenero": caso["subgenero"]})
    return faixas


async def selos(client: httpx.AsyncClient, faixas: list[dict]) -> list[tuple[dict, str | None, bool]]:
    """(faixa, selo, achada no Deezer) — selo None = falha, "" = álbum sem selo."""
    semaforo = asyncio.Semaphore(CONCORRENCIA)

    async def uma(faixa: dict):
        async with semaforo:
            info = await deezer_client.get_track_info(client, faixa["artista"], faixa["nome"])
            if not info.get("deezer_id"):
                return faixa, None, False
            return faixa, await deezer_client.get_track_label(client, info["deezer_id"]), True

    return await asyncio.gather(*(uma(f) for f in faixas))


def relatorio(resultados: list[tuple[dict, str | None, bool]], golden: bool) -> None:
    total = len(resultados)
    achadas = sum(1 for _, _, ok in resultados if ok)
    com_selo = [(f, s) for f, s, _ in resultados if s]
    falhas = sum(1 for _, s, ok in resultados if ok and s is None)
    print(f"  achadas no Deezer: {achadas}/{total}")
    print(f"  com selo: {len(com_selo)}/{total} ({100 * len(com_selo) / max(total, 1):.0f}%)"
          f"   falhas de rede: {falhas}")

    contagem = Counter(s for _, s in com_selo)
    print(f"  selos distintos: {len(contagem)}")
    acumulado = 0
    for i, (selo, n) in enumerate(contagem.most_common(), 1):
        acumulado += n
        print(f"  {selo:40} {n:4d}   (top {i}: {100 * acumulado / max(len(com_selo), 1):.0f}% das com selo)")

    if golden:
        print("\n  selo × subgênero da referência:")
        por_selo: dict[str, Counter] = defaultdict(Counter)
        for f, s in com_selo:
            por_selo[s][f["subgenero"]] += 1
        for selo, subs in sorted(por_selo.items(), key=lambda kv: -sum(kv[1].values())):
            print(f"  {selo:40} {dict(subs)}")


async def main_async(n: int, golden: bool) -> None:
    # A medição não pode mexer no banco: o gravar da correspondência vira no-op.
    enrichment_store.put_deezer_match = lambda *args, **kwargs: None
    if golden:
        faixas = faixas_do_golden()
        print(f"Conjunto dourado: {len(faixas)} casos")
    else:
        from scripts.medir_fontes_psy import faixas_psy  # lê o banco só neste modo

        faixas = list(faixas_psy().values())[:n]
        print(f"Biblioteca: {len(faixas)} faixas psy")
    async with httpx.AsyncClient() as client:
        relatorio(await selos(client, faixas), golden)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mede selos do Deezer nas faixas psy.")
    parser.add_argument("--faixas", type=int, default=150, help="quantas faixas da biblioteca consultar")
    parser.add_argument("--golden", action="store_true", help="usar o conjunto dourado em vez da biblioteca")
    args = parser.parse_args()
    asyncio.run(main_async(args.faixas, args.golden))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
