"""Aplica a taxonomia ao que já está guardado no banco.

    cd backend
    python -m scripts.reclassificar_generos --dry-run   # mostra o que mudaria
    python -m scripts.reclassificar_generos             # grava

Por que existe: a taxonomia (`app/taxonomy.py`) classifica no momento da
análise, então playlists analisadas ANTES dela continuam guardadas com os
rótulos antigos. A página de Perfil lê os resumos guardados, e a da playlist lê
a análise guardada — as duas mostrariam o gráfico velho até cada playlist ser
analisada de novo.

Analisar de novo custaria uma varredura completa do Spotify, e esta conta já foi
suspensa por 18 horas uma vez por volume de requisição. Não é preciso: as tags
já estão dentro de cada análise e de cada resumo. Este script relê o que está em
disco, reclassifica e grava. **Não chama Spotify, Last.fm, Deezer nem modelo
nenhum** — dá para rodar com a internet desligada.

É idempotente: rodar duas vezes não muda nada na segunda. E só toca gênero
(`genres`, `tags`, as distribuições e a contagem de faixas sem gênero); BPM,
prévia, data de adição, popularidade e tudo o que vem do Spotify ficam como
estão.
"""
import argparse
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import analysis_store, db, profile_store, reclassify  # noqa: E402
from app.models import PlaylistAnalysis  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(message)s")

TOPO = 12


def _topo_dos_resumos(resumos: list[dict]) -> Counter:
    """A distribuição de gêneros da conta, como o Perfil a monta."""
    contador: Counter = Counter()
    for resumo in resumos:
        for faixa in resumo.get("tracks") or []:
            for genero in faixa.get("genres") or []:
                contador[genero.strip().lower()] += 1
    return contador


def _tabela(antes: Counter, depois: Counter) -> None:
    print(f"\n{'ANTES':38} | DEPOIS")
    print("-" * 38 + "-+-" + "-" * 38)
    a, d = antes.most_common(TOPO), depois.most_common(TOPO)
    for i in range(max(len(a), len(d))):
        esq = f"{a[i][0][:26]:28} {a[i][1]:5d}" if i < len(a) else ""
        dir_ = f"{d[i][0][:26]:28} {d[i][1]:5d}" if i < len(d) else ""
        print(f"{esq:38} | {dir_}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reclassifica gênero no banco, sem rede.")
    parser.add_argument("--dry-run", action="store_true", help="só mostra o que mudaria")
    parser.add_argument(
        "--force",
        action="store_true",
        help="reclassifica também o que já está na versão atual da taxonomia",
    )
    args = parser.parse_args()

    print(f"Banco: {db.db_path()}")
    print(f"Taxonomia em vigor: v{reclassify.current_version()}")

    # ── resumos de perfil ───────────────────────────────────────────────────
    linhas = db.query(
        "SELECT playlist_id, digest FROM playlist_digests WHERE format = ?", (profile_store.VERSION,)
    )
    resumos = []
    for linha in linhas:
        try:
            resumos.append((linha["playlist_id"], json.loads(linha["digest"])))
        except (ValueError, TypeError):
            print(f"  resumo ilegível em {linha['playlist_id']}, pulando")

    pendentes = [(pid, r) for pid, r in resumos if args.force or not reclassify.is_current(r)]

    antes = _topo_dos_resumos([r for _, r in resumos])
    faixas_mudadas = 0
    novos: list[tuple[str, dict]] = []
    for playlist_id, resumo in pendentes:
        novo, mudadas = reclassify.digest(resumo)
        faixas_mudadas += mudadas
        novos.append((playlist_id, novo))
    # A distribuição "depois" considera também os resumos que não precisam mudar.
    por_id = dict(novos)
    depois = _topo_dos_resumos([por_id.get(pid, r) for pid, r in resumos])

    print(f"\nResumos de perfil: {len(resumos)}")
    print(f"  já na taxonomia em vigor (pulados): {len(resumos) - len(pendentes)}")
    print(f"  a reclassificar: {len(pendentes)}")
    print(f"  faixas com gênero reescrito: {faixas_mudadas}")
    print(f"  rótulos distintos no gráfico: {len(antes)} -> {len(depois)}")
    print(f"  votos de gênero: {sum(antes.values())} -> {sum(depois.values())}")
    _tabela(antes, depois)

    # ── análises completas ──────────────────────────────────────────────────
    linhas = db.query(
        "SELECT playlist_id, analysis FROM playlist_analyses WHERE format = ?",
        (analysis_store.ANALYSIS_FORMAT,),
    )
    analises: list[tuple[str, PlaylistAnalysis]] = []
    for linha in linhas:
        try:
            analises.append((linha["playlist_id"], PlaylistAnalysis.model_validate_json(linha["analysis"])))
        except ValueError:
            print(f"  análise ilegível em {linha['playlist_id']}, pulando")

    a_refazer = [(pid, a) for pid, a in analises if args.force or not reclassify.is_current(a)]
    refeitas = [(pid, reclassify.analysis(a)) for pid, a in a_refazer]

    print(f"\nAnálises completas: {len(analises)}")
    print(f"  já na taxonomia em vigor (puladas): {len(analises) - len(a_refazer)}")
    for (pid, antiga), (_, nova) in zip(a_refazer, refeitas):
        rotulos_antes = [g.label for g in antiga.genre_distribution[:4]]
        rotulos_depois = [g.label for g in nova.genre_distribution[:4]]
        print(f"  {antiga.playlist.name[:34]:36} {rotulos_antes} -> {rotulos_depois}")

    if args.dry_run:
        print("\n--dry-run: nada foi gravado.")
        return 0

    if not novos and not refeitas:
        print("\nTudo já está na taxonomia em vigor. Nada a fazer (--force reclassifica mesmo assim).")
        return 0

    agora = time.time()
    with db.transaction() as conn:
        for playlist_id, resumo in novos:
            # `saved_at` novo para o import dos JSONs antigos (INSERT OR IGNORE)
            # nunca voltar a sobrepor o resumo reclassificado.
            resumo["saved_at"] = agora
            conn.execute(
                "UPDATE playlist_digests SET digest = ?, saved_at = ? WHERE playlist_id = ?",
                (db.dumps(resumo), agora, playlist_id),
            )
        for playlist_id, analise in refeitas:
            conn.execute(
                "UPDATE playlist_analyses SET analysis = ?, saved_at = ? WHERE playlist_id = ?",
                (analise.model_dump_json(), agora, playlist_id),
            )

    # O que já foi lido neste processo (e no servidor em pé) está velho.
    profile_store.clear_memo()
    print(f"\nGravado: {len(novos)} resumo(s) e {len(refeitas)} análise(s).")
    print("Reinicie o backend para o cache em memória soltar o que leu antes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
