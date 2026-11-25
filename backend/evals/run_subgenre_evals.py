"""Mede a precisão do subgênero contra rótulos de referência externa.

    python -m evals.run_subgenre_evals              # resumo e tabela por subgênero
    python -m evals.run_subgenre_evals --verboso    # mostra também a evidência de cada faixa

O conjunto (`subgenre_golden.yaml`) são faixas cujo subgênero vem de uma fonte
de fora — os exemplos do Guia de Psytrance e as páginas do Beatport —, com as
entradas (tags do Last.fm e BPM do Deezer) CONGELADAS por
`congelar_subgeneros.py`. Aqui nada toca a rede: cada faixa passa por
`taxonomy.classify` e `subgenre.blend`, como em produção.

Números:
  precisão confiante  dos casos em que o app AFIRMOU um subgênero, quantos batem
                      com a referência (o que o usuário vê como fato)
  taxa de incerto     fração dos casos em que o app se absteve (`unsure` ou sem
                      nenhuma evidência) — a contrapartida honesta da precisão
  top-2               fração dos casos em que a referência está entre os dois
                      primeiros do blend, afirmado ou não

O processo sai com 1 quando a precisão confiante cai abaixo de
`limiares.precisao_confiante` ou a taxa de incerto passa de `limiares.max_incerto`.
Sem nenhum caso confiante, a precisão é indefinida e o piso não se aplica — o
primeiro caso confiante que aparecer já passa a ser cobrado.
"""
import argparse
import collections
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import subgenre, taxonomy  # noqa: E402

GOLDEN_PATH = Path(__file__).resolve().parent / "subgenre_golden.yaml"


def _rodar_caso(caso: dict) -> dict:
    artista = taxonomy.as_tags(caso.get("artista") or [])
    faixa = taxonomy.as_tags(caso.get("faixa_tags") or [])
    classificacao = taxonomy.classify(artist_tags=artista, track_tags=faixa)
    resultado = subgenre.blend(
        classificacao.genre, artist_tags=artista, track_tags=faixa, bpm=caso.get("bpm")
    )
    esperado = caso["subgenero"]
    afirmou = resultado.subgenre is not None
    return {
        "id": caso["id"],
        "faixa": caso.get("faixa", ""),
        "esperado": esperado,
        "genero": classificacao.genre,
        "resultado": resultado,
        "afirmou": afirmou,
        "confiante_ok": afirmou and resultado.subgenre == esperado,
        "top2": esperado in [label for label, _ in resultado.blend[:2]],
    }


def golden(verboso: bool) -> int:
    dados = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    limiares = dados.get("limiares") or {}
    casos = dados.get("casos") or []
    resultados = [_rodar_caso(c) for c in casos]
    total = len(resultados)

    confiantes = [r for r in resultados if r["afirmou"]]
    acertos = sum(1 for r in confiantes if r["confiante_ok"])
    incertos = total - len(confiantes)
    top2 = sum(1 for r in resultados if r["top2"])

    precisao = acertos / len(confiantes) if confiantes else None
    taxa_incerto = incertos / total if total else 1.0

    print(f"Conjunto dourado de subgênero — {total} faixa(s) com rótulo de referência externa\n")
    for r in resultados:
        res = r["resultado"]
        if r["afirmou"]:
            veredito = "ok  " if r["confiante_ok"] else "ERRO "
        else:
            veredito = "inc "
        if verboso or veredito == "ERRO ":
            print(f"[{veredito}] {r['id']}  (esperado: {r['esperado']})")
            print(f"         {r['faixa']}")
            print(f"         -> {res.subgenre or '—'}  inclinação {res.lean or '—'}  confiança {res.confidence:.2f}"
                  f"{'  INCERTO' if res.unsure else ''}")
            if verboso:
                for e in res.evidence:
                    print(f"            · {e.source}: {e.detail}")
    print()

    por_sub: dict[str, list] = collections.defaultdict(list)
    for r in resultados:
        por_sub[r["esperado"]].append(r)
    print(f"{'subgênero':22}{'n':>3}{'afirmou':>9}{'acertou':>9}{'incerto':>9}{'top-2':>7}")
    for nome in sorted(por_sub):
        rs = por_sub[nome]
        afirmados = [r for r in rs if r["afirmou"]]
        print(
            f"{nome:22}{len(rs):>3}{len(afirmados):>9}{sum(1 for r in afirmados if r['confiante_ok']):>9}"
            f"{len(rs) - len(afirmados):>9}{sum(1 for r in rs if r['top2']):>7}"
        )
    print()

    texto_precisao = f"{precisao:.3f}" if precisao is not None else "indefinida"
    print(f"precisão confiante : {acertos}/{len(confiantes)} = {texto_precisao}   "
          f"(piso {limiares.get('precisao_confiante', 0):.2f})")
    print(f"taxa de incerto    : {incertos}/{total} = {taxa_incerto:.3f}   "
          f"(teto {limiares.get('max_incerto', 1):.2f})")
    print(f"top-2              : {top2}/{total} = {top2 / total if total else 0:.3f}")

    abaixo_do_piso = precisao is not None and precisao < limiares.get("precisao_confiante", 0)
    reprovou = abaixo_do_piso or taxa_incerto > limiares.get("max_incerto", 1)
    print()
    print("REPROVADO: abaixo do limiar" if reprovou else "aprovado")
    return 1 if reprovou else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Precisão do subgênero contra referências externas.")
    parser.add_argument("-v", "--verboso", action="store_true", help="mostra a evidência de cada faixa")
    args = parser.parse_args()
    return golden(args.verboso)


if __name__ == "__main__":
    raise SystemExit(main())
