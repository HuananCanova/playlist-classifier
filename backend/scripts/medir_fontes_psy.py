"""Mede o quanto Deezer (BPM) e Discogs (estilos) ajudam a separar o psytrance.

    cd backend
    python -m scripts.medir_fontes_psy [--bpm 50] [--discogs 30]

Lê as faixas psy já guardadas (análises e resumos de perfil), consulta as duas
fontes numa amostra e imprime dois relatórios. **Não grava nada no banco.**
O Discogs só roda com `DISCOGS_TOKEN` definido; sem ele, a parte é pulada.
"""
import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app import analysis_store, db, deezer_client, discogs_client, enrichment_store, profile_store  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models import PlaylistAnalysis  # noqa: E402

GENERO = "psytrance"
PAUSA_DISCOGS_S = 1.1  # o Discogs limita a 60 requisições por minuto


def _eh_psy(genero: str | None, generos: list[str]) -> bool:
    return (genero or "").lower() == GENERO or GENERO in [g.lower() for g in generos]


def _album_guardado(track_id: str) -> str | None:
    linha = db.query_one("SELECT data FROM spotify_tracks WHERE track_id = ?", (track_id,))
    if linha is None:
        return None
    try:
        album = json.loads(linha["data"]).get("album")
    except ValueError:
        return None
    return (album.get("name") if isinstance(album, dict) else album) or None


def faixas_psy() -> dict[str, dict]:
    """track_id -> {artista, nome, album}, sem repetir faixa entre playlists."""
    faixas: dict[str, dict] = {}

    for linha in db.query(
        "SELECT analysis FROM playlist_analyses WHERE format = ?", (analysis_store.ANALYSIS_FORMAT,)
    ):
        try:
            analise = PlaylistAnalysis.model_validate_json(linha["analysis"])
        except ValueError:
            continue
        for t in analise.tracks:
            if t.artists and _eh_psy(t.genre, t.genres):
                faixas.setdefault(
                    t.track_id, {"artista": t.artists[0], "nome": t.name, "album": t.album}
                )

    for linha in db.query("SELECT digest FROM playlist_digests WHERE format = ?", (profile_store.VERSION,)):
        try:
            resumo = json.loads(linha["digest"])
        except (ValueError, TypeError):
            continue
        for t in resumo.get("tracks") or []:
            if t.get("artists") and _eh_psy(None, t.get("genres") or []) and t["id"] not in faixas:
                faixas[t["id"]] = {"artista": t["artists"][0], "nome": t["name"], "album": None}

    for track_id, faixa in faixas.items():
        if not faixa["album"]:
            faixa["album"] = _album_guardado(track_id)
    return faixas


async def medir_bpm(client: httpx.AsyncClient, faixas: list[dict]) -> None:
    print(f"\n== BPM (Deezer) em {len(faixas)} faixas psy ==")
    infos = await deezer_client.get_many(client, [(f["artista"], f["nome"]) for f in faixas])
    bpms = sorted(i["bpm"] for i in infos if i.get("bpm") and i["bpm"] > 0)
    achadas = sum(1 for i in infos if i.get("deezer_id"))
    if faixas:
        print(f"  achadas no Deezer: {achadas}/{len(faixas)}")
        print(f"  com BPM > 0: {len(bpms)}/{len(faixas)} ({100 * len(bpms) / len(faixas):.0f}%)")
    print(f"  valores: {bpms}")


async def medir_discogs(client: httpx.AsyncClient, albuns: list[tuple[str, str]], token: str) -> None:
    print(f"\n== Estilos (Discogs) em {len(albuns)} álbuns ==")
    estilos: Counter = Counter()
    achados = 0
    for i, (artista, album) in enumerate(albuns):
        if i:
            await asyncio.sleep(PAUSA_DISCOGS_S)
        resultado = await discogs_client.get_release_styles(client, artista, album, token)
        if resultado is None:
            continue
        achados += 1
        estilos.update(resultado)
    print(f"  álbuns achados: {achados}/{len(albuns)}")
    for estilo, n in estilos.most_common():
        print(f"  {estilo:32} {n:4d}")


async def main_async(n_bpm: int, n_discogs: int) -> None:
    # `get_track_info` guarda o que acha em `deezer_matches`; a medição não pode
    # mexer no banco, então esse gravar vira no-op (a leitura do que já existe fica).
    enrichment_store.put_deezer_match = lambda *args, **kwargs: None
    faixas = faixas_psy()
    print(f"Banco: {db.db_path()}")
    print(f"Faixas psy distintas: {len(faixas)}")

    token = get_settings().discogs_token
    async with httpx.AsyncClient() as client:
        if n_bpm > 0:
            await medir_bpm(client, list(faixas.values())[:n_bpm])
        if n_discogs > 0:
            if not token:
                print("\nDiscogs pulado: defina DISCOGS_TOKEN em backend/.env.")
            else:
                albuns = list(
                    dict.fromkeys((f["artista"], f["album"]) for f in faixas.values() if f["album"])
                )[:n_discogs]
                await medir_discogs(client, albuns, token)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mede BPM e estilos do Discogs nas faixas psy.")
    parser.add_argument("--bpm", type=int, default=50, help="quantas faixas consultar no Deezer")
    parser.add_argument("--discogs", type=int, default=30, help="quantos álbuns consultar no Discogs")
    args = parser.parse_args()
    asyncio.run(main_async(args.bpm, args.discogs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
