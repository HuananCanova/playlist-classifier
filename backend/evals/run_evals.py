"""Roda o conjunto dourado contra o provedor configurado.

Por que existe: o app suporta Claude e Groq atrás da mesma interface, e até aqui
a única forma de comparar os dois era ler as respostas e formar uma opinião.
Aqui a comparação vira contagem — quantos casos passam, quantos tokens custaram,
quanto tempo levaram.

O que NÃO acontece aqui: nenhuma chamada ao Spotify, Last.fm ou Deezer. A camada
de dados é trocada pelas fixtures dos testes, então o custo de rodar isto é só o
do modelo. Numa conta que já levou ban por volume de requisições, um harness que
varre a API a cada execução seria inutilizável.

Uso:
    cd backend
    python -m evals.run_evals                 # provedor do .env
    python -m evals.run_evals --provider groq
    python -m evals.run_evals --caso faixa-parecidas
"""
import argparse
import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ai_tools, metrics, vector_store  # noqa: E402
from app.config import get_settings  # noqa: E402
from tests.conftest import _tracks  # noqa: E402

GOLDEN = Path(__file__).parent / "golden.yaml"

# Os nomes da fixture seguem este formato; qualquer coisa nesse formato que
# apareça numa resposta e não exista na fixture é alucinação.
PADRAO_FAIXA = re.compile(r"\b[A-Z][a-z]+ Track \d+\b")

PLAYLIST_ID = "p1"
TRACK_ID = "shoegaze-0"


def _fixtures():
    from app.models import PlaylistAnalysis, PlaylistSummary, TrackDetail

    tracks = _tracks()
    analysis = PlaylistAnalysis(
        playlist=PlaylistSummary(id=PLAYLIST_ID, name="Mistura", track_count=len(tracks)),
        tracks=tracks,
        genre_distribution=[],
        subgenre_distribution=[],
        top_artists=[],
        tracks_missing_genre=0,
    )
    detail = TrackDetail(
        track_id=TRACK_ID,
        name=tracks[0].name,
        artists=tracks[0].artists,
        album=tracks[0].album,
        duration_ms=280_000,
        tags=tracks[0].subgenre_tags,
        artist_tags=["shoegaze", "dream pop"],
        bpm=96.0,
        preview_url="https://exemplo/preview.mp3",
        match_confidence="alta",
        matched_title=tracks[0].name,
    )
    return analysis, detail


async def _preparar(analysis, detail, tmpdir: Path):
    """Troca a camada de dados por fixtures e monta um índice descartável."""

    async def fake_analysis(_token, _playlist_id):
        return analysis

    async def fake_detail(_token, _track_id):
        return detail

    # ai_tools importou os nomes diretamente, então é lá que precisam ser trocados.
    ai_tools.build_playlist_analysis = fake_analysis
    ai_tools.build_track_detail = fake_detail

    vector_store.CHROMA_PATH = tmpdir / "chroma"
    vector_store._collection = None
    await vector_store.index_tracks(
        [
            {
                "track_id": t.track_id,
                "nome": t.name,
                "artistas": t.artists,
                "album": t.album,
                "tags": t.subgenre_tags,
            }
            for t in analysis.tracks
        ]
    )


async def _rodar_caso(caso: dict, nomes_validos: set[str]) -> dict:
    from app.ai_chat import stream_chat

    escopo = caso["scope"]
    kwargs = {"playlist_id": PLAYLIST_ID} if escopo == "playlist" else {"track_id": TRACK_ID}

    partes: list[str] = []
    ferramentas: list[str] = []
    erro: str | None = None

    async for linha in stream_chat(
        "token-de-teste",
        [{"role": "user", "content": caso["pergunta"]}],
        **kwargs,
    ):
        if not linha.startswith("data: "):
            continue
        evento = json.loads(linha[6:])
        if evento["type"] == "text":
            partes.append(evento["delta"])
        elif evento["type"] == "tool":
            ferramentas.append(evento["name"])
        elif evento["type"] == "error":
            erro = evento["message"]

    resposta = "".join(partes)
    falhas: list[str] = []

    if erro:
        falhas.append(f"erro do agente: {erro}")
    if not resposta.strip() and not erro:
        falhas.append("resposta vazia")

    for esperada in caso.get("ferramentas") or []:
        if esperada not in ferramentas:
            falhas.append(f"não chamou `{esperada}` (chamou: {ferramentas or 'nenhuma'})")

    for trecho in caso.get("contem") or []:
        if trecho.lower() not in resposta.lower():
            falhas.append(f"não menciona {trecho!r}")

    for trecho in caso.get("nao_contem") or []:
        if trecho.lower() in resposta.lower():
            falhas.append(f"menciona o proibido {trecho!r}")

    inventadas = {n for n in PADRAO_FAIXA.findall(resposta) if n not in nomes_validos}
    if inventadas:
        falhas.append(f"faixas inventadas: {sorted(inventadas)}")

    return {
        "id": caso["id"],
        "ok": not falhas,
        "falhas": falhas,
        "ferramentas": ferramentas,
        "resposta": resposta,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Roda o conjunto dourado do agente.")
    parser.add_argument("--provider", choices=["anthropic", "groq"])
    parser.add_argument("--caso", help="Roda só um caso, pelo id.")
    parser.add_argument("--verbose", action="store_true", help="Mostra as respostas.")
    args = parser.parse_args()

    if args.provider:
        get_settings().chat_provider = args.provider

    from app.ai_chat import active_provider

    provider = active_provider()
    if provider is None:
        print(
            "Nenhum provedor de IA configurado — defina ANTHROPIC_API_KEY ou "
            "GROQ_API_KEY em backend/.env.",
            file=sys.stderr,
        )
        return 2

    casos = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["casos"]
    if args.caso:
        casos = [c for c in casos if c["id"] == args.caso]
        if not casos:
            print(f"Caso {args.caso!r} não existe.", file=sys.stderr)
            return 2

    analysis, detail = _fixtures()
    nomes_validos = {t.name for t in analysis.tracks}

    # `ignore_cleanup_errors`: no Windows o Chroma mantém o sqlite aberto e a
    # remoção do diretório falha. O índice é descartável, então o erro de
    # limpeza não deve derrubar uma execução que passou.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        await _preparar(analysis, detail, Path(tmp))

        metrics.reset()
        print(f"Provedor: {provider} — {len(casos)} caso(s)\n")

        resultados = []
        for caso in casos:
            r = await _rodar_caso(caso, nomes_validos)
            resultados.append(r)
            marca = "PASSOU" if r["ok"] else "FALHOU"
            print(f"[{marca}] {r['id']}")
            for f in r["falhas"]:
                print(f"         {f}")
            if args.verbose and r["resposta"]:
                print(f"         > {r['resposta'][:300].strip()}")

        vector_store._collection = None

    passaram = sum(1 for r in resultados if r["ok"])
    print(f"\n{passaram}/{len(resultados)} casos passaram")

    resumo = metrics.summary().get("por_provedor", {}).get(provider)
    if resumo:
        print(
            f"tokens: {resumo['input_tokens']} entrada / {resumo['output_tokens']} saída"
            f" | ttft mediano: {resumo['ttft_mediano']}s"
            f" | total mediano: {resumo['total_mediano']}s"
            f" | ferramentas por turno: {resumo['ferramentas_por_turno']}"
        )

    return 0 if passaram == len(resultados) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
