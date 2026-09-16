"""Estatísticas do perfil a partir dos resumos de playlist.

O perfil é um **retrato do gosto**, não um relatório do acervo. Só entra aqui o
que descreve *o que* a pessoa ouve: gêneros, estilos, artistas, época, o quanto
o gosto é concentrado ou espalhado, onde ele cai entre o hit e o garimpo, e em
que andamento. Contagem de faixas explícitas, faixas repetidas entre playlists e
afins são fatos da biblioteca, não do gosto — ficaram de fora de propósito.

Função pura, sem rede nem disco: recebe os resumos já carregados e devolve os
números do painel. Roda a cada consulta do frontend durante a varredura, então
precisa ser barata — algumas milhares de faixas levam milissegundos.

Duas contagens diferentes aparecem aqui, e a distinção importa:

- **faixas únicas** (deduplicadas por id): o acervo. Artistas, gêneros, décadas
  e duração contam cada música uma vez, senão quem repete uma faixa em cinco
  playlists veria esse artista inflado.
- **adições** (faixa + playlist): o gesto de escolher. A linha do gosto conta
  adições, porque pôr a mesma música numa segunda playlist é escolhê-la de novo.
"""
import math
from collections import Counter, defaultdict
from datetime import datetime

TOP_ARTISTS = 12
TOP_GENRES = 12
TOP_TAGS = 18

# Séries do gráfico do gosto ao longo do tempo. Cinco + "outros" = seis cores,
# o teto validado da paleta em charts/chartKit.js.
TASTE_SERIES = 5

# Garimpos: as faixas menos populares do acervo. O teto evita chamar de garimpo
# uma faixa que só é um pouco menos conhecida que as outras.
DEEP_CUTS = 8
DEEP_CUT_MAX_POPULARITY = 35

# Onde cada faixa cai entre o desconhecido e o hit, pela popularidade do Spotify.
POPULARITY_BANDS = [
    ("Fora do radar", 0, 20),
    ("Nicho", 20, 40),
    ("Conhecido", 40, 60),
    ("Popular", 60, 80),
    ("Hit", 80, 101),
]

# Os mesmos nomes de andamento da página da playlist (components/BpmChart.jsx).
TEMPO_ZONES = [
    ("Lento", 0, 90),
    ("Moderado", 90, 115),
    ("Dançante", 115, 135),
    ("Acelerado", 135, 160),
    ("Frenético", 160, 10_000),
]

def _year(added_at: str | None) -> int | None:
    # "2024-03-18T21:04:11Z" -> 2024. Faixas antigas vêm como
    # "1970-01-01T00:00:00Z" quando o Spotify não sabe a data; isso não é escolha.
    if not added_at or len(added_at) < 4 or added_at.startswith("1970"):
        return None
    try:
        return int(added_at[:4])
    except ValueError:
        return None


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


def _bands(values: list[float], bands: list[tuple[str, float, float]]) -> list[dict]:
    """Distribui valores em faixas ordenadas [início, fim). Devolve todas as
    faixas, inclusive as vazias: o buraco no meio de uma escala é informação."""
    if not values:
        return []
    return [
        {"label": label, "from": lo, "to": hi, "count": sum(1 for v in values if lo <= v < hi)}
        for label, lo, hi in bands
    ]


def _taste_timeline(additions: list[tuple[int, frozenset[str]]], top_keys: list[str]) -> list[dict]:
    """Quanto de cada gênero principal você escolheu, ano a ano.

    Cada adição vale 1, repartida igualmente entre os gêneros do topo que ela
    tem — assim uma faixa com três desses gêneros não pesa três vezes mais que
    uma com um só, e a altura da coluna continua sendo "faixas escolhidas".
    Uma faixa com gênero, mas nenhum do topo, vai inteira para "outros"; sem
    gênero nenhum, não entra (seria inventar uma escolha que não se conhece).

    Anos sem nenhuma adição entram zerados, para o eixo não encurtar o silêncio.
    """
    if not additions or not top_keys:
        return []

    slot_of = {key: i for i, key in enumerate(top_keys)}
    width = len(top_keys) + 1  # + "outros"
    per_year: dict[int, list[float]] = {}
    totals: Counter = Counter()

    for year, genres in additions:
        counts = per_year.setdefault(year, [0.0] * width)
        matched = [slot_of[g] for g in genres if g in slot_of]
        if matched:
            for i in matched:
                counts[i] += 1 / len(matched)
        elif genres:
            counts[-1] += 1
        else:
            continue
        totals[year] += 1

    if not totals:
        return []

    return [
        {
            "year": y,
            "tracks": totals.get(y, 0),
            "counts": [round(v, 2) for v in per_year.get(y, [0.0] * width)],
        }
        for y in range(min(totals), max(totals) + 1)
    ]


def build_profile_stats(playlists: list[dict], digests: dict[str, dict]) -> dict | None:
    """`playlists`: resumos da listagem, na ordem do Spotify. `digests`: por id."""
    covered = [p for p in playlists if digests.get(p["id"])]
    if not covered:
        return None

    tracks: dict[str, dict] = {}
    playlists_of: dict[str, set[str]] = defaultdict(set)
    additions: list[tuple[int, frozenset[str]]] = []
    first_added: str | None = None
    playlist_rows = []

    for p in covered:
        digest = digests[p["id"]]
        genre_counts: Counter = Counter()
        artists_here: set[str] = set()
        duration = 0
        seen_here: set[str] = set()

        for t in digest.get("tracks", []):
            tid = t.get("id")
            if not tid:
                continue
            tracks.setdefault(tid, t)
            if tid not in seen_here:
                playlists_of[tid].add(p["name"])
                seen_here.add(tid)

            duration += t.get("duration_ms") or 0
            artists_here.update(t.get("artists") or [])
            genres = frozenset(g.lower() for g in t.get("genres") or [])
            for g in genres:
                genre_counts[g] += 1

            year = _year(t.get("added_at"))
            if year:
                additions.append((year, genres))
                stamp = t["added_at"]
                if first_added is None or stamp < first_added:
                    first_added = stamp

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
    bpms = [t["bpm"] for t in unique if t.get("bpm")]
    durations = [t.get("duration_ms") or 0 for t in unique]

    taste_keys = [key for key, _ in genre_counter.most_common(TASTE_SERIES)]

    # Os garimpos: o fundo do poço da popularidade, do mais obscuro ao menos.
    deep_cuts = sorted(
        (t for t in unique if (t.get("popularity") or 0) <= DEEP_CUT_MAX_POPULARITY and t.get("popularity") is not None),
        key=lambda t: (t["popularity"], t.get("name") or ""),
    )[:DEEP_CUTS]

    years.sort(key=lambda yt: yt[0])
    oldest = years[0] if years else None

    return {
        "library": {
            "unique_tracks": n,
            "unique_artists": len(artist_tracks),
            "total_duration_ms": sum(durations),
            "avg_popularity": round(sum(popularity) / len(popularity), 1) if popularity else None,
            "popularity_known": len(popularity),
            "avg_bpm": round(sum(bpms) / len(bpms), 1) if bpms else None,
            "bpm_known": len(bpms),
            "genre_diversity": round(effective_count(genre_counter), 1),
            "artist_diversity": round(effective_count(artist_tracks), 1),
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
        "popularity_bands": _bands(popularity, POPULARITY_BANDS),
        "tempo_zones": _bands(bpms, TEMPO_ZONES),
        "taste_timeline": {
            "genres": [genre_label[key] for key in taste_keys],
            "years": _taste_timeline(additions, taste_keys),
        },
        "deep_cuts": [
            {
                "id": t["id"],
                "name": t.get("name"),
                "artists": t.get("artists") or [],
                "image": t.get("image"),
                "popularity": t["popularity"],
                "genre": (t.get("genres") or [None])[0],
            }
            for t in deep_cuts
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
