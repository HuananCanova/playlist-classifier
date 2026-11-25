"""Mede a precisão da classificação de gênero.

Dois modos:

    python -m evals.run_genre_evals              # conjunto dourado, com nota
    python -m evals.run_genre_evals --cobertura   # o que falta na taxonomia

O conjunto dourado (`genre_golden.yaml`) é julgamento humano sobre faixas reais:
responde "o app acerta o gênero?" com um número, e falha o processo quando a
precisão cai abaixo do limiar declarado no YAML — serve em CI.

A cobertura lê os resumos de playlist em disco (`backend/.profile_cache`, o que
a conta já analisou) e mede quanto do vocabulário real a taxonomia alcança,
listando o que ficou de fora em ordem de frequência. Não é nota, é fila de
trabalho: as primeiras linhas são sempre o melhor lugar para gastar os próximos
cinco minutos editando o YAML.

Nenhum dos dois toca a rede: sem Spotify, sem Last.fm, sem modelo de IA.
"""
import argparse
import collections
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import taxonomy  # noqa: E402

GOLDEN_PATH = Path(__file__).resolve().parent / "genre_golden.yaml"
DIGESTS_PATH = Path(__file__).resolve().parent.parent / ".profile_cache"


def _carregar_golden() -> dict:
    return yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))


def _rodar_caso(caso: dict) -> dict:
    resultado = taxonomy.classify(
        artist_tags=taxonomy.as_tags(caso.get("artista") or []),
        track_tags=taxonomy.as_tags(caso.get("faixa_tags") or []),
    )
    esperado_genero = caso.get("genero")
    esperado_sub = caso.get("subgenero")
    esperado_unresolved = caso.get("unresolved")

    falhas = []
    if resultado.genre != esperado_genero:
        falhas.append(f"gênero: esperava {esperado_genero!r}, veio {resultado.genre!r}")
    if esperado_sub is not None and resultado.subgenre != esperado_sub:
        falhas.append(f"subgênero: esperava {esperado_sub!r}, veio {resultado.subgenre!r}")
    if esperado_unresolved is not None:
        faltando = [t for t in esperado_unresolved if t not in resultado.unresolved]
        if faltando:
            falhas.append(f"pendências não apontadas: {faltando}")

    return {
        "id": caso.get("id", "?"),
        "faixa": caso.get("faixa", ""),
        "genero_ok": resultado.genre == esperado_genero,
        # Só conta como caso de subgênero quando o conjunto cobra subgênero.
        "subgenero_cobrado": esperado_sub is not None,
        "subgenero_ok": esperado_sub is not None and resultado.subgenre == esperado_sub,
        "falhas": falhas,
        "resultado": resultado,
    }


def golden(verboso: bool) -> int:
    dados = _carregar_golden()
    casos = dados.get("casos") or []
    limiares = dados.get("limiares") or {}
    resultados = [_rodar_caso(c) for c in casos]

    acertos = sum(1 for r in resultados if r["genero_ok"])
    com_sub = [r for r in resultados if r["subgenero_cobrado"]]
    acertos_sub = sum(1 for r in com_sub if r["subgenero_ok"])

    precisao = acertos / len(resultados) if resultados else 0.0
    precisao_sub = acertos_sub / len(com_sub) if com_sub else 1.0

    print(f"Conjunto dourado de gênero — {len(resultados)} faixa(s) rotulada(s) à mão\n")
    for r in resultados:
        marca = "ok  " if not r["falhas"] else "FALHA"
        if r["falhas"] or verboso:
            print(f"[{marca}] {r['id']}")
            if r["faixa"]:
                print(f"         {r['faixa']}")
            for f in r["falhas"]:
                print(f"         {f}")
            if verboso and not r["falhas"]:
                res = r["resultado"]
                print(
                    f"         -> {res.genre} / {res.subgenre} "
                    f"(confiança {res.confidence}, por {', '.join(res.evidence) or '—'})"
                )

    print()
    print(f"gênero    : {acertos}/{len(resultados)} = {precisao:.3f}   (limiar {limiares.get('genero', 0):.2f})")
    print(f"subgênero : {acertos_sub}/{len(com_sub)} = {precisao_sub:.3f}   (limiar {limiares.get('subgenero', 0):.2f})")

    # Distribuição da confiança: um classificador que acerta sempre com
    # confiança 0,3 está acertando por sorte, e isso tem que ficar visível.
    confiancas = [r["resultado"].confidence for r in resultados if r["resultado"].genre]
    if confiancas:
        media = sum(confiancas) / len(confiancas)
        print(f"confiança : média {media:.2f}, mínima {min(confiancas):.2f}, máxima {max(confiancas):.2f}")

    reprovou = precisao < limiares.get("genero", 0) or precisao_sub < limiares.get("subgenero", 0)
    print()
    print("REPROVADO: abaixo do limiar" if reprovou else "aprovado")
    return 1 if reprovou else 0


def _vocabulario() -> collections.Counter:
    """As tags do acervo já analisado, com quantas faixas usam cada uma."""
    vocab: collections.Counter = collections.Counter()
    if not DIGESTS_PATH.is_dir():
        return vocab
    for path in DIGESTS_PATH.glob("*.json"):
        try:
            digest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for track in digest.get("tracks") or []:
            for tag in (track.get("genres") or []) + (track.get("tags") or []):
                vocab[tag.strip().lower()] += 1
    return vocab


def cobertura(limite: int) -> int:
    vocab = _vocabulario()
    if not vocab:
        print(f"Nenhum resumo em {DIGESTS_PATH} — analise alguma playlist primeiro.")
        return 0

    tabela = taxonomy.load()
    massa = sum(vocab.values())
    classificado = descartado = pendente = 0
    fila: collections.Counter = collections.Counter()

    for tag, n in vocab.items():
        if tabela.resolve(tag) is not None:
            classificado += n
        elif tabela.discarded(tag):
            descartado += n
        else:
            pendente += n
            fila[tag] = n

    print(f"Vocabulário real: {len(vocab)} tags distintas, {massa} usos em faixas\n")
    print(f"  classificado        {classificado:6d}  {100 * classificado / massa:5.1f}%")
    print(f"  descartado (ignore) {descartado:6d}  {100 * descartado / massa:5.1f}%")
    print(f"  sem casa no YAML    {pendente:6d}  {100 * pendente / massa:5.1f}%")
    print(f"\nTaxonomia v{tabela.version}: {len(tabela.genres)} gêneros, "
          f"{len(tabela.index)} entradas, {len(tabela.ignored)} descartes\n")

    if fila:
        print(f"Fila de trabalho — {limite} tags sem casa, por impacto:")
        for tag, n in fila.most_common(limite):
            print(f"  {n:5d}  {tag}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Precisão e cobertura da classificação de gênero.")
    parser.add_argument("--cobertura", action="store_true", help="relatório do vocabulário real em vez do conjunto dourado")
    parser.add_argument("--limite", type=int, default=30, help="tags listadas na fila de trabalho (padrão: 30)")
    parser.add_argument("-v", "--verboso", action="store_true", help="mostra também os casos que passaram")
    args = parser.parse_args()

    if args.cobertura:
        return cobertura(args.limite)
    return golden(args.verboso)


if __name__ == "__main__":
    raise SystemExit(main())
