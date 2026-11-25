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


def _share(track: dict, name: str | None) -> float:
    for label, share in track.get("subgenre_blend") or []:
        if label == name:
            return share
    return 0


def _collapse(digests: dict[str, dict]) -> dict[str, dict]:
    """Uma faixa guardada em várias playlists vira um registro só.

    Cada cópia pode ter viés/dúvida/parcela diferentes. Vence a cópia cujo viés
    tem a maior parcela na própria mistura; empate: a confiante; ainda empate:
    a da playlist de menor id. Cópias sem os campos de subgênero são ignoradas.
    Registro: {track, playlists: [ids]} — as playlists onde alguma cópia válida está.
    """
    out: dict[str, dict] = {}
    for pid in sorted(digests):
        for track in (digests[pid] or {}).get("tracks") or []:
            if "subgenre_lean" not in track:
                continue
            lean = track["subgenre_lean"]
            key = (lean is None, -_share(track, lean), bool(track.get("subgenre_unsure")))
            rec = out.get(track["id"])
            if rec is None:
                out[track["id"]] = {"track": track, "key": key, "playlists": [pid]}
                continue
            if pid not in rec["playlists"]:
                rec["playlists"].append(pid)
            if key < rec["key"]:  # ids em ordem: no empate fica o primeiro
                rec["track"], rec["key"] = track, key
    return out


def library_subgenres(digests: dict[str, dict]) -> list[dict]:
    """Subgêneros dos gêneros presentes no acervo, com faixas únicas por viés.

    Devolve também os de contagem zero, para a tela mostrar o vocabulário
    inteiro com as faixas de BPM. Ordem: a da taxonomia.
    """
    confident: dict[str, int] = {}
    unsure: dict[str, int] = {}
    present: set[str] = set()
    for rec in _collapse(digests).values():
        track = rec["track"]
        present.update(g for g in track.get("genres") or [] if isinstance(g, str))
        lean = track["subgenre_lean"]
        info = taxonomy.subgenre_info(lean) if lean else None
        if info is None:
            continue
        present.add(info.genre)
        bucket = unsure if track.get("subgenre_unsure") else confident
        bucket[info.name] = bucket.get(info.name, 0) + 1

    rows = []
    for genre in taxonomy.load().genres:
        if genre not in present:
            continue
        for info in taxonomy.subgenres_of(genre):
            rows.append({
                **_info_dict(info),
                "confident": confident.get(info.name, 0),
                "unsure": unsure.get(info.name, 0),
            })
    return rows


def subgenre_tracks(digests: dict[str, dict], playlists: list[PlaylistSummary], name: str) -> dict | None:
    """As faixas de um subgênero, separadas em "é X" e "puxa para X".

    None se o nome não é um subgênero da taxonomia. Só entram resumos de
    playlists da listagem da conta; cada faixa aparece uma vez (veja
    `_collapse`), com todas as playlists onde está.
    """
    info = taxonomy.subgenre_info(name)
    if info is None:
        return None
    names = {p.id: p.name for p in playlists}
    found = []
    for rec in _collapse({k: v for k, v in digests.items() if k in names}).values():
        track = rec["track"]
        if track["subgenre_lean"] != info.name:
            continue
        found.append({
            "id": track["id"], "name": track.get("name"), "artists": track.get("artists") or [],
            "image": track.get("image"), "bpm": track.get("bpm"),
            "share": _share(track, info.name),
            "playlists": [{"id": pid, "name": names[pid]} for pid in rec["playlists"]],
            "_unsure": bool(track.get("subgenre_unsure")),
        })

    def lista(unsure: bool) -> list[dict]:
        itens = [{k: v for k, v in e.items() if k != "_unsure"} for e in found if e["_unsure"] == unsure]
        return sorted(itens, key=lambda t: -t["share"])

    return {"info": _info_dict(info), "confident": lista(False), "leaning": lista(True)}
