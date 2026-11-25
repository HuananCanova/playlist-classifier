"""Visão do acervo por subgênero: contagens e faixas — funções puras.

Lê só o que o resumo de cada playlist já guarda (`subgenre_lean`,
`subgenre_unsure`, `subgenre_blend`). Resumos antigos, sem esses campos, são
ignorados em vez de quebrar a página.
"""
from . import taxonomy
from .models import PlaylistSummary


def _info_dict(info: taxonomy.SubgenreInfo) -> dict:
    return {
        "genre": info.genre,
        "name": info.name,
        "bpm": list(info.bpm) if info.bpm else None,
        "about": info.about,
        "source": info.source,
    }


def _tracks(digests: dict[str, dict]):
    for pid, digest in digests.items():
        for track in (digest or {}).get("tracks") or []:
            yield pid, track


def library_subgenres(digests: dict[str, dict]) -> list[dict]:
    """Subgêneros dos gêneros presentes no acervo, com faixas únicas por viés.

    Devolve também os de contagem zero, para a tela mostrar o vocabulário
    inteiro com as faixas de BPM. Ordem: a da taxonomia.
    """
    confident: dict[str, set[str]] = {}
    unsure: dict[str, set[str]] = {}
    present: set[str] = set()
    for _, track in _tracks(digests):
        present.update(g for g in track.get("genres") or [] if isinstance(g, str))
        lean = track.get("subgenre_lean")
        info = taxonomy.subgenre_info(lean) if lean else None
        if info is None:
            continue
        present.add(info.genre)
        bucket = unsure if track.get("subgenre_unsure") else confident
        bucket.setdefault(info.name, set()).add(track.get("id"))

    rows = []
    for genre in taxonomy.load().genres:
        if genre not in present:
            continue
        for info in taxonomy.subgenres_of(genre):
            rows.append({
                **_info_dict(info),
                "confident": len(confident.get(info.name, ())),
                "unsure": len(unsure.get(info.name, ())),
            })
    return rows


def _share(track: dict, name: str) -> float:
    for label, share in track.get("subgenre_blend") or []:
        if label == name:
            return share
    return 0


def subgenre_tracks(digests: dict[str, dict], playlists: list[PlaylistSummary], name: str) -> dict | None:
    """As faixas de um subgênero, separadas em "é X" e "puxa para X".

    None se o nome não é um subgênero da taxonomia. Só entram resumos de
    playlists da listagem da conta; cada faixa aparece uma vez, com todas as
    playlists onde está.
    """
    info = taxonomy.subgenre_info(name)
    if info is None:
        return None
    names = {p.id: p.name for p in playlists}
    found: dict[str, dict] = {}
    for pid, track in _tracks({k: v for k, v in digests.items() if k in names}):
        if track.get("subgenre_lean") != info.name:
            continue
        entry = found.get(track["id"])
        if entry is None:
            entry = found[track["id"]] = {
                "id": track["id"], "name": track.get("name"), "artists": track.get("artists") or [],
                "image": track.get("image"), "bpm": track.get("bpm"),
                "share": _share(track, info.name), "playlists": [],
                "_unsure": bool(track.get("subgenre_unsure")),
            }
        if not any(p["id"] == pid for p in entry["playlists"]):
            entry["playlists"].append({"id": pid, "name": names[pid]})

    def lista(unsure: bool) -> list[dict]:
        itens = [{k: v for k, v in e.items() if k != "_unsure"} for e in found.values() if e["_unsure"] == unsure]
        return sorted(itens, key=lambda t: -t["share"])

    return {"info": _info_dict(info), "confident": lista(False), "leaning": lista(True)}
