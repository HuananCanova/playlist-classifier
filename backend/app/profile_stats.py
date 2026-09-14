"""Estatísticas do perfil a partir dos resumos de playlist.

Função pura, sem rede nem disco: recebe os resumos já carregados e devolve os
números do painel. Roda a cada consulta do frontend durante a varredura, então
precisa ser barata — algumas milhares de faixas levam milissegundos.

Duas contagens diferentes aparecem aqui, e a distinção importa:

- **faixas únicas** (deduplicadas por id): o acervo. Artistas, gêneros, décadas
  e duração contam cada música uma vez, senão quem repete uma faixa em cinco
  playlists veria esse artista inflado.
- **entradas** (faixa + playlist): o gesto de adicionar. A linha do tempo conta
  entradas, porque pôr a mesma música numa segunda playlist também é atividade.
"""
import math
from collections import Counter, defaultdict
from datetime import datetime

TOP_ARTISTS = 12
TOP_GENRES = 12
TOP_TAGS = 18
TOP_REPEATED = 8


def _month(added_at: str | None) -> str | None:
    # "2024-03-18T21:04:11Z" -> "2024-03". Faixas muito antigas vêm como
    # "1970-01-01T00:00:00Z" quando o Spotify não sabe a data; isso não é atividade.
    if not added_at or len(added_at) < 7 or added_at.startswith("1970"):
        return None
    return added_at[:7]


def _month_range(first: str, last: str) -> list[str]:
    y, m = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    out = []
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def effective_count(counts: Counter) -> float:
    """Número efetivo de categorias: exp da entropia de Shannon.

    Lê-se como "equivale a N gêneros igualmente frequentes". Diferente de contar
    gêneros distintos, uma playlist com 95% de um gênero e 20 aparições soltas
    dá perto de 1, não 21.
    """
    total = sum(counts.values())
    if not total:
        return 0.0
    h = -sum((c / total) * math.log(c / total) for c in counts.values() if c)
    return math.exp(h)


def build_profile_stats(playlists: list[dict], digests: dict[str, dict]) -> dict | None:
    """`playlists`: resumos da listagem, na ordem do Spotify. `digests`: por id."""
    covered = [p for p in playlists if digests.get(p["id"])]
    if not covered:
        return None

    tracks: dict[str, dict] = {}
    playlists_of: dict[str, list[str]] = defaultdict(list)
    added_months: Counter = Counter()
    first_added: str | None = None
    playlist_rows = []

    for p in covered:
        digest = digests[p["id"]]
        genre_counts: Counter = Counter()
        artists_here: set[str] = set()
        duration = 0
        last_added: str | None = None
        seen_here: set[str] = set()

        for t in digest.get("tracks", []):
            tid = t.get("id")
            if not tid:
                continue
            tracks.setdefault(tid, t)
            if tid not in seen_here:
                playlists_of[tid].append(p["name"])
                seen_here.add(tid)

            duration += t.get("duration_ms") or 0
            artists_here.update(t.get("artists") or [])
            for g in t.get("genres") or []:
                genre_counts[g.lower()] += 1

            month = _month(t.get("added_at"))
            if month:
                added_months[month] += 1
                stamp = t["added_at"]
                if first_added is None or stamp < first_added:
                    first_added = stamp
                if last_added is None or stamp > last_added:
                    last_added = stamp

        top_genre = genre_counts.most_common(1)
        playlist_rows.append(
            {
                "id": p["id"],
                "name": p["name"],
                "image": p.get("image"),
                "tracks": len(digest.get("tracks", [])),
                "duration_ms": duration,
                "artists": len(artists_here),
                "top_genre": top_genre[0][0] if top_genre else None,
                "genre_diversity": round(effective_count(genre_counts), 1),
                "last_added": last_added,
            }
        )

    unique = list(tracks.values())
    n = len(unique)

    # Artistas: faixas únicas por artista, e em quantas playlists ele aparece.
    artist_tracks: Counter = Counter()
    artist_playlists: dict[str, set[str]] = defaultdict(set)
    genre_counter: Counter = Counter()
    genre_label: dict[str, str] = {}
    tag_counter: Counter = Counter()
    tag_label: dict[str, str] = {}
    with_genre = 0
    decades: Counter = Counter()
    years: list[tuple[int, dict]] = []

    for t in unique:
        for a in t.get("artists") or []:
            artist_tracks[a] += 1
            artist_playlists[a].update(playlists_of[t["id"]])

        genres = {g.lower(): g for g in t.get("genres") or []}
        if genres:
            with_genre += 1
        for key, label in genres.items():
            genre_counter[key] += 1
            genre_label.setdefault(key, label)

        # Tags da faixa que não são os gêneros amplos do artista: o nível fino.
        for tag in t.get("tags") or []:
            key = tag.lower()
            if key in genres:
                continue
            tag_counter[key] += 1
            tag_label.setdefault(key, tag)

        year = t.get("release_year")
        if year:
            decades[(year // 10) * 10] += 1
            years.append((year, t))

    popularity = [t["popularity"] for t in unique if t.get("popularity") is not None]
    explicit = [t["explicit"] for t in unique if t.get("explicit") is not None]
    bpms = [t["bpm"] for t in unique if t.get("bpm")]
    durations = [t.get("duration_ms") or 0 for t in unique]

    timeline = []
    if added_months:
        months = sorted(added_months)
        timeline = [{"month": m, "count": added_months.get(m, 0)} for m in _month_range(months[0], months[-1])]

    repeated = sorted(
        (t for t in unique if len(playlists_of[t["id"]]) >= 2),
        key=lambda t: (-len(playlists_of[t["id"]]), t.get("name") or ""),
    )[:TOP_REPEATED]

    years.sort(key=lambda yt: yt[0])
    oldest = years[0] if years else None

    entries = sum(r["tracks"] for r in playlist_rows)

    return {
        "library": {
            "unique_tracks": n,
            "entries": entries,
            "repeated_entries": entries - n,
            "unique_artists": len(artist_tracks),
            "total_duration_ms": sum(durations),
            "avg_duration_ms": round(sum(durations) / n) if n else 0,
            "avg_popularity": round(sum(popularity) / len(popularity), 1) if popularity else None,
            "popularity_known": len(popularity),
            "explicit_share": round(sum(explicit) / len(explicit), 3) if explicit else None,
            "avg_bpm": round(sum(bpms) / len(bpms), 1) if bpms else None,
            "bpm_known": len(bpms),
            "genre_diversity": round(effective_count(genre_counter), 1),
            "tracks_with_genre": with_genre,
            "first_added": first_added,
            "median_release_year": years[len(years) // 2][0] if years else None,
            "oldest_track": (
                {
                    "year": oldest[0],
                    "name": oldest[1].get("name"),
                    "artists": oldest[1].get("artists") or [],
                    "id": oldest[1].get("id"),
                }
                if oldest
                else None
            ),
        },
        "top_artists": [
            {"name": name, "tracks": count, "playlists": len(artist_playlists[name])}
            for name, count in artist_tracks.most_common(TOP_ARTISTS)
        ],
        "top_genres": [
            {"label": genre_label[key], "count": count}
            for key, count in genre_counter.most_common(TOP_GENRES)
        ],
        "top_tags": [
            {"label": tag_label[key], "count": count}
            for key, count in tag_counter.most_common(TOP_TAGS)
        ],
        "decades": [{"decade": d, "count": decades[d]} for d in sorted(decades)],
        "added_timeline": timeline,
        "repeated_tracks": [
            {
                "id": t["id"],
                "name": t.get("name"),
                "artists": t.get("artists") or [],
                "image": t.get("image"),
                "playlists": playlists_of[t["id"]],
            }
            for t in repeated
        ],
        "playlists": playlist_rows,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_index_stats(metadatas: list[dict]) -> dict | None:
    """Artistas e estilos a partir do índice da busca.

    O índice cobre todas as playlists já indexadas, mesmo as que ainda não têm
    resumo do perfil — então dá um retrato do acervo sem chamar o Spotify. O que
    ele não sabe: em que playlist cada faixa está, quando entrou, duração, ano.
    As tags do índice misturam gênero do artista e tags da faixa.
    """
    if not metadatas:
        return None

    artists: Counter = Counter()
    tags: Counter = Counter()
    tag_label: dict[str, str] = {}
    for meta in metadatas:
        for a in (meta.get("artistas") or "").split(", "):
            if a:
                artists[a] += 1
        for tag in (meta.get("tags") or "").split(", "):
            key = tag.strip().lower()
            if key:
                tags[key] += 1
                tag_label.setdefault(key, tag.strip())

    return {
        "tracks": len(metadatas),
        "unique_artists": len(artists),
        "top_artists": [{"name": n, "tracks": c} for n, c in artists.most_common(TOP_ARTISTS)],
        "top_tags": [{"label": tag_label[k], "count": c} for k, c in tags.most_common(TOP_TAGS)],
    }
