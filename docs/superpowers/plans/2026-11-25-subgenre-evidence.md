# Subgenre Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every track an explainable subgenre blend (tags + Deezer BPM against reference ranges + optional Discogs styles), mark weak cases "unsure", and let the owner browse tracks by subgenre in a playlist and across the library.

**Architecture:** A new pure module (`app/subgenre.py`) turns per-source evidence into a blend; network lookups happen before it and their results are stored per track (`track_evidence` table) so stored analyses can be reclassified offline. An opt-in enrichment job fills that table for the library without touching Spotify. The frontend reads the new optional fields on tracks and digests.

**Tech Stack:** Python 3.12, FastAPI, httpx, Pydantic v2, SQLite (`app/db.py` migrations), pytest + pytest-asyncio; React 18 + Vite, hand-made charts (`charts/chartKit.js`).

**Spec:** `docs/superpowers/specs/2026-11-25-subgenre-evidence-design.md`

## Global Constraints

- No new Spotify calls. Track lists come from stored analyses/digests; routes may use `get_playlist_summaries(request)` exactly as `app/profile.py` already does.
- `taxonomy.classify` and everything in `app/subgenre.py` stay pure (no network, no DB); network results are passed in.
- Network failures are never stored as "no data" (existing rule in `enrichment_store.py`).
- Do not bump `profile_store.VERSION` or the analysis format so stored data is invalidated: new fields are optional with defaults; old rows must load and render.
- Reference data comes from psytranceguide.com v1.2 (cite the URL per range); descriptions are our own words, never copied text; no guide audio stored.
- Unsure is never counted as a hit in evals.
- Code comments, UI copy and README text in Portuguese, matching the codebase; this plan and the spec are in English.
- The owner runs Docker Compose; the database is the `data` volume. Anything run "against real data" runs via `docker compose exec backend …`.
- Tests touch no network (`tests/conftest.py` rule); mock httpx with `httpx.MockTransport`.

## Review Focus

1. Deezer reports half-time BPM for psy (e.g. 72 for a 144 track): the tempo source should read it as double-time and say so in the evidence, not vote "psychill". → test in Task 3.
2. Tracks outside psytrance (rock, techno) or genres with no subgenres: no crash, no blanket "unsure"; tag-only blends behave like today's subgenre. → tests in Task 3.
3. Old stored analyses/digests without the new fields: API validates, playlist/track/subgenre pages render, reclassify upgrades them. → tests in Tasks 4 and 6, frontend guards in Tasks 11–13.
4. Enrichment job interrupted, restarted, or hitting Last.fm/Deezer errors: failures not stored, job resumes from what is missing, tracks without evidence keep their tag-only blend. → tests in Task 7.
5. Account isolation: the subgenre page and enrichment job only see playlists in the requesting account's listing. → test in Task 10.

---

### Task 1: Measure the sources (BPM and Discogs gates)

**Files:**
- Create: `backend/app/discogs_client.py`
- Modify: `backend/app/config.py` (add `discogs_token: str | None = None`)
- Modify: `backend/.env.example` (add commented `DISCOGS_TOKEN=`)
- Create: `backend/scripts/medir_fontes_psy.py`
- Test: `backend/tests/test_discogs_client.py`
- Modify: `docs/superpowers/specs/2026-11-25-subgenre-evidence-design.md` (append "Gate results")

**Interfaces:**
- Produces: `async def get_release_styles(client: httpx.AsyncClient, artist: str, album: str, token: str) -> list[str] | None` — styles of the best-matching release/master; `[]` = found with no styles, `None` = not found or request failed. Uses `GET https://api.discogs.com/database/search?type=release&artist=…&release_title=…` with header `Authorization: Discogs token=…` and a `User-Agent`; picks the first result whose normalized title matches the album (reuse `deezer_client._parecido`-style comparison; write a local helper).

- [ ] **Step 1: Write failing tests** in `test_discogs_client.py`: `test_returns_styles_of_matching_release` (MockTransport returns a search result with `title: "Porat - Ritual Resonance"`, `style: ["Psy-Trance", "Progressive Trance"]` → `["Psy-Trance", "Progressive Trance"]`), `test_none_when_no_result_matches` (results for another album → `None`), `test_none_on_http_error` (500 → `None`), `test_sends_token_header`.
- [ ] **Step 2: Run** `cd backend && python -m pytest tests/test_discogs_client.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** `get_release_styles` and the config field.
- [ ] **Step 4: Run** the same command → PASS.
- [ ] **Step 5: Write `scripts/medir_fontes_psy.py`** (`python -m scripts.medir_fontes_psy [--bpm 50] [--discogs 30]`): reads psy tracks (genre or `genres` contains `psytrance`) from `playlist_analyses` + `playlist_digests`; for up to N tracks calls `deezer_client.get_track_info` and prints how many have `bpm` > 0, with the BPM values; for up to M distinct albums (album name from analyses, falling back to `spotify_tracks.data`) calls `get_release_styles` and prints a style frequency table. Skips Discogs with a message when `DISCOGS_TOKEN` is unset. Writes nothing to the DB.
- [ ] **Step 6: Run against the real data:** `docker compose exec backend python -m scripts.medir_fontes_psy` (owner must add `DISCOGS_TOKEN` to `backend/.env` first for the Discogs half; ask them). Expected: two reports printed.
- [ ] **Step 7: Record results** in a "Gate results" section of the spec: BPM coverage % on psy; Discogs styles seen. Apply the spec rules: Discogs passes only if styles separate psy subgenres beyond "Psy-Trance / Goa Trance / Progressive Trance". **Stop and report both numbers to the owner** before Task 8.
- [ ] **Step 8: Commit**

```bash
git add backend/app/discogs_client.py backend/app/config.py backend/.env.example backend/scripts/medir_fontes_psy.py backend/tests/test_discogs_client.py docs/superpowers/specs/2026-11-25-subgenre-evidence-design.md
git commit -m "Mede cobertura de BPM e estilos do Discogs no psy"
```

### Task 2: Taxonomy carries subgenre reference data

**Files:**
- Modify: `backend/app/taxonomy.py`
- Modify: `backend/app/taxonomy.yaml` (psytrance block; bump `version` to 2)
- Test: `backend/tests/test_taxonomy.py`

**Interfaces:**
- Produces:
  - `class SubgenreInfo(NamedTuple): genre: str; name: str; bpm: tuple[float, float] | None; about: str | None; source: str | None`
  - `def subgenre_info(name: str) -> SubgenreInfo | None`
  - `def subgenres_of(genre: str) -> list[SubgenreInfo]` (YAML order)
  - `def tag_weight_factor(tag: str) -> float` — `WEAK_FACTOR = 0.3` for aliases listed under `weak:`, else `1.0`
- A subgenre value in YAML may be the old list of aliases or a mapping `{aliases: [...], weak: [...], bpm: [lo, hi], about: "...", source: "..."}`. `weak` aliases resolve to the subgenre like normal aliases.

Psytrance subgenres after this task (name: bpm, aliases to add beyond existing ones):

| subgenre | bpm | notes |
|---|---|---|
| progressive psytrance | 130–140 | add alias `psyprog` |
| full-on | 140–148 | |
| night full-on | 145–150 | aliases `night fullon`, `twilight` |
| offbeat | 134–140 | aliases `offbeat psy`, `offbeat psytrance` |
| darkpsy | 140–155 | remove `forest psy` from its aliases |
| forest psy | 150–160 | aliases `forest`, `forest psytrance`, `forest darkpsy` (check `forest` is not in `ignore`/`ambiguos`; if it is, move it here and note why) |
| hitech | 170–200 | |
| psycore | 170–250 | |
| goa trance | 135–150 | `goa` moves to `weak:` |
| psy-techno | 125–137 | aliases `psytechno` |
| nitzhonot | 145–160 | |
| hypnotic psy | 140–150 | |
| psychill | 90–120 | |
| dark progressive | — | keep, no bpm |
| suomi | — | aliases `suomisaundi`, `suomi psy` |

Every entry with bpm gets `source: https://psytranceguide.com` and a one-line `about` in Portuguese written by us. Add `psychodelic` to the parent's aliases.

- [ ] **Step 1: Write failing tests:** `test_subgenre_mapping_form_loads` (`subgenre_info("full-on").bpm == (140.0, 148.0)`), `test_old_list_form_still_loads` (a rock subgenre still resolves), `test_forest_is_its_own_subgenre` (`resolve("forest psy") == Node("psytrance", "forest psy")`), `test_offbeat_resolves`, `test_goa_is_weak` (`resolve("goa").subgenre == "goa trance"` and `tag_weight_factor("goa") == 0.3`, `tag_weight_factor("goa trance") == 1.0`), `test_subgenres_of_psytrance_in_yaml_order`, `test_every_bpm_range_has_source`.
- [ ] **Step 2: Run** `python -m pytest tests/test_taxonomy.py -v` → new tests FAIL.
- [ ] **Step 3: Implement** the parser change and functions; apply `tag_weight_factor` inside `_votes` (multiply each tag's weight before normalizing). Edit the YAML as tabled.
- [ ] **Step 4: Run** `python -m pytest -q` (whole suite) and `python -m evals.run_genre_evals` → all PASS; genre accuracy unchanged. If a golden psy subgenre case flips because of `goa`/`forest`, leave it for Task 9 and note it in the commit message.
- [ ] **Step 5: Commit** `git commit -m "Taxonomia: subgêneros de psy com faixa de BPM e fonte"`

### Task 3: Evidence model (pure)

**Files:**
- Create: `backend/app/subgenre.py`
- Test: `backend/tests/test_subgenre.py`

**Interfaces:**
- Consumes: `taxonomy.resolve`, `taxonomy.subgenres_of`, `taxonomy.tag_weight_factor`, `taxonomy.Tag`.
- Produces:
  - `class Evidence(NamedTuple): source: str; says: str | None; detail: str`
  - `class SourceResult(NamedTuple): name: str; distribution: dict[str, float]; evidence: list[Evidence]` (distribution sums to 1)
  - `class SubgenreResult(NamedTuple): blend: list[tuple[str, float]]; lean: str | None; subgenre: str | None; confidence: float; unsure: bool; evidence: list[Evidence]`
  - `EMPTY_RESULT = SubgenreResult([], None, None, 0.0, False, [])`
  - `def tags_source(name: str, genre: str, tags: list[Tag]) -> SourceResult | None` — used twice, as `"track_tags"` and `"artist_tags"`
  - `def tempo_source(genre: str, bpm: float | None) -> SourceResult | None`
  - `def release_source(genre: str, styles: list[str] | None) -> SourceResult | None`
  - `def blend(genre: str | None, *, artist_tags: list[Tag], track_tags: list[Tag], bpm: float | None = None, styles: list[str] | None = None, extra: Iterable[SourceResult] = ()) -> SubgenreResult`
- Initial constants (tuned in Task 9, kept in this module):
  - `SOURCE_WEIGHTS = {"track_tags": 1.0, "tempo": 0.8, "release": 0.6, "artist_tags": 0.4}`; an `extra` source uses `SOURCE_WEIGHTS.get(name, 0.6)`
  - `TEMPO_FALLOFF_BPM = 6.0`; `UNSURE_MIN_SHARE = 0.5`

Rules the tests pin:
- Sources only consider subgenres of `genre`; a source with nothing for this genre returns `None` (abstains).
- `tempo_source`: `bpm` None or ≤ 0 → abstain. Likelihood per subgenre with a range: 1.0 inside `[lo, hi]`, else `max(0, 1 - distance / TEMPO_FALLOFF_BPM)`; normalized. If every likelihood is 0 and doubling `bpm` gives a non-zero result, use `bpm * 2` and the evidence detail says it was read as double-time. All zero → abstain.
- `blend`: weighted sum of the non-abstaining sources' distributions, normalized → `blend` sorted by share desc then name. `lean` = top label. `confidence` = top share.
- `unsure` is True when: only `artist_tags` voted; or top share < `UNSURE_MIN_SHARE`; or the two heaviest voting sources have different top labels. `subgenre` = `lean` if not unsure, else None.
- `genre` None or genre without subgenres → `EMPTY_RESULT`. No source votes → `EMPTY_RESULT` (not unsure: there is nothing to be unsure about).
- Evidence: one `Evidence` per voting source, Portuguese detail, e.g. `Evidence("tempo", "full-on", "146 BPM; full-on vai de 140 a 148")`.

- [ ] **Step 1: Write failing tests:** `test_tempo_inside_range_votes_that_subgenre` (146 → full-on top), `test_tempo_overlap_shares` (138 → progressive and offbeat both > 0), `test_tempo_half_time_read_as_double` (72 → full-on/psytrance range, detail mentions double), `test_tempo_zero_abstains`, `test_artist_only_is_unsure` (artist tags `full-on` only → `unsure`, `lean == "full-on"`, `subgenre is None`), `test_track_tags_and_tempo_agree_is_confident`, `test_sources_disagree_is_unsure` (track tags `darkpsy`, tempo 132), `test_tempo_separates_two_tracks_by_same_artist` (same artist tags, bpm 132 vs 152 → different leans), `test_rock_track_tag_only_behaves` (rock with track tag `hard rock` → subgenre `hard rock`, not unsure), `test_genre_without_subgenres_is_empty`, `test_no_votes_is_empty_not_unsure`, `test_extra_source_is_combined`, `test_weak_goa_loses_to_real_signal` (artist tags `goa` + track tag `full-on` → full-on).
- [ ] **Step 2: Run** `python -m pytest tests/test_subgenre.py -v` → FAIL.
- [ ] **Step 3: Implement** `app/subgenre.py`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "Modelo de evidência de subgênero (função pura)"`

### Task 4: Per-track evidence storage and new optional fields

**Files:**
- Modify: `backend/app/db.py` (migration 3)
- Create: `backend/app/evidence_store.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/profile_store.py` (`digest_from_analysis` adds fields)
- Test: `backend/tests/test_evidence_store.py`, `backend/tests/test_persistence.py`

**Interfaces:**
- Migration 3:

```sql
CREATE TABLE track_evidence (
    track_id    TEXT PRIMARY KEY,
    artist_tags TEXT,   -- JSON [{name, weight}] or NULL = not fetched
    track_tags  TEXT,
    bpm         REAL,   -- NULL = unknown
    deezer_id   INTEGER,
    styles      TEXT,   -- JSON [str] or NULL = not fetched
    updated_at  REAL NOT NULL
);
```

- `@dataclass class TrackEvidence: track_id: str; artist_tags: list[Tag] | None = None; track_tags: list[Tag] | None = None; bpm: float | None = None; deezer_id: int | None = None; styles: list[str] | None = None`
- `def get_many(track_ids: list[str]) -> dict[str, TrackEvidence]`; `def put(ev: TrackEvidence) -> None` (merge: a None field never overwrites a stored value); `def missing(track_ids: list[str]) -> list[str]` (ids with no row, or with `artist_tags`/`track_tags` NULL, or with bpm NULL and deezer_id NULL). No TTL.
- Models: `class SubgenreShare(BaseModel): label: str; share: float`; `class EvidenceLine(BaseModel): source: str; says: str | None = None; detail: str`. On `TrackGenreInfo` and `TrackDetail`: `subgenre_blend: list[SubgenreShare] = []`, `subgenre_lean: str | None = None`, `subgenre_confidence: float | None = None`, `subgenre_unsure: bool = False`, `subgenre_evidence: list[EvidenceLine] = []`. On `PlaylistAnalysis`: `class SubgenreBar(BaseModel): label: str; confident: float; unsure: float` and `subgenre_bars: list[SubgenreBar] = []`.
- Digest track dict gains `subgenre_lean`, `subgenre_unsure`, `subgenre_blend` (list of `[label, share]`, shares rounded to 3).
- `def subgenre_fields(result: subgenre.SubgenreResult) -> dict` in `models.py` or `subgenre.py` (builder's choice; name it exactly this) mapping a result to the five track fields.

- [ ] **Step 1: Write failing tests:** `test_put_and_get_roundtrip`, `test_put_does_not_erase_known_values`, `test_missing_lists_incomplete_rows`, `test_old_analysis_json_without_new_fields_loads` (load a stored analysis dict lacking the fields → defaults), `test_digest_has_subgenre_fields`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `python -m pytest -q` → PASS.
- [ ] **Step 5: Commit** `git commit -m "Evidência por faixa no banco e campos de subgênero opcionais"`

### Task 5: New analyses compute blends and store evidence

**Files:**
- Modify: `backend/app/genre_analysis.py` (`_build`)
- Modify: `backend/app/tracks.py` (`build_track_detail`)
- Test: `backend/tests/test_genre_analysis_subgenre.py`

**Interfaces:**
- Consumes: `subgenre.blend`, `subgenre_fields`, `evidence_store.get_many/put`, `SubgenreBar`.
- In `_build`: after `taxonomy.classify`, call `blend(classification.genre, artist_tags=artist_tags, track_tags=lastfm_tags, bpm=deezer["bpm"], styles=<stored styles or None>)`. Track `subgenre` becomes the blend's `subgenre` (confident only); `subgenre_counter` counts `lean`. Build `subgenre_bars`: per label, sum of shares split into `confident` (tracks not unsure) and `unsure`. Save one `TrackEvidence` per track with the separated weighted tags and the Deezer bpm/id (only when the lookups succeeded).
- `build_track_detail` gets the same fields the same way.

- [ ] **Step 1: Write failing test** `test_build_stores_separated_tags_and_blend` (monkeypatch `get_artist_tags`, `get_track_tags`, `get_deezer_many`, Spotify client → one psy track with track tag `full-on`, bpm 146 → analysis track has `subgenre == "full-on"`, `subgenre_bars[0].label == "full-on"`, and `evidence_store.get_many` returns separated tags with weights) and `test_unsure_track_counts_in_bars_unsure_part`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `python -m pytest -q` → PASS.
- [ ] **Step 5: Commit** `git commit -m "Análise nova calcula a mistura de subgêneros e guarda a evidência"`

### Task 6: Offline reclassification uses stored evidence

**Files:**
- Modify: `backend/app/reclassify.py`
- Modify: `backend/scripts/reclassificar_generos.py`
- Test: `backend/tests/test_taxonomy.py` (or new `tests/test_reclassify_subgenre.py`)

**Interfaces:**
- `def track(faixa: TrackGenreInfo, evidence: TrackEvidence | None = None) -> TrackGenreInfo` — with evidence: classify genre from separated tags and set blend fields from `blend(...)` using evidence tags/bpm/styles; without: today's merged-tag path, and blend from the merged tags passed as `artist_tags` (so old data becomes tag-only, honestly unsure when artist-level).
- `def analysis(...)` and `def digest(...)` load evidence with `evidence_store.get_many` for their track ids and fill the new fields (digest tracks get `subgenre_lean/unsure/blend`; analyses get `subgenre_bars`).
- `def account(playlist_ids: list[str]) -> dict` — reclassifies the stored analyses and digests of those playlists; returns counts.
- `is_current` also requires the subgenre fields to exist, so old rows get upgraded once.
- Script prints, in addition to today's tables: subgenre lean counts before/after for psytrance, unsure rate, and how many tracks had stored evidence.

- [ ] **Step 1: Write failing tests:** `test_reclassify_with_evidence_uses_tempo`, `test_reclassify_without_evidence_is_tag_only`, `test_old_digest_gets_subgenre_fields`, `test_reclassify_is_idempotent`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `python -m pytest -q` → PASS.
- [ ] **Step 5: Run against real data:** `docker compose exec backend python -m scripts.reclassificar_generos --dry-run` → report prints psy lean counts and unsure rate.
- [ ] **Step 6: Commit** `git commit -m "Reclassificação offline com a evidência guardada"`

### Task 7: Enrichment job

**Files:**
- Create: `backend/app/enrichment_job.py`
- Create: `backend/app/subgenres.py` (router `prefix="/api/subgenres"`; include in `main.py`)
- Test: `backend/tests/test_enrichment_job.py`

**Interfaces:**
- `@dataclass class EnrichProgress: running: bool = False; total: int = 0; done: int = 0; current: str | None = None; errors: list[str] = field(default_factory=list); started_at: float | None = None; finished_at: float | None = None`
- `def pending_tracks(digests: dict[str, dict]) -> list[dict]` — unique tracks (id, name, artists, album) from the digests whose evidence is missing (`evidence_store.missing`), ordered: tracks whose `genres` include a genre with bpm ranges first, then the rest.
- `async def start(account: str, digests: dict[str, dict]) -> EnrichProgress` (one job per account, like `indexer.start`); `def progress_dict(account: str) -> dict` (also returns `pending` count and `estimated_minutes`); `async def cancel(account: str) -> None`.
- Per track: Last.fm artist tags for each credited artist (separate) and track tags, Deezer match when bpm unknown, Discogs styles only when `settings.discogs_token` is set **and** `DISCOGS_ENABLED = True` in this module (set by Task 8). Use existing clients and caches; concurrency `LASTFM_CONCURRENCY` from `genre_analysis`. A lookup that raised is left None (not stored) and the error counted. At the end: run Task 6's `reclassify.account(playlist_ids)` for this account's playlists.
- Routes: `GET /api/subgenres/enrich` → `progress_dict`; `POST /api/subgenres/enrich` → start; `DELETE` → cancel. Account and digests resolved like `profile.get_profile` (`account_key`, `get_playlist_summaries`, `profile_store.load`).

- [ ] **Step 1: Write failing tests:** `test_pending_orders_psy_first`, `test_job_fills_evidence` (mocked clients), `test_failed_lookup_not_stored_and_retried_next_run` (Last.fm raises for one track → its tags stay None; second run fetches it), `test_restart_skips_completed_tracks`, `test_no_spotify_calls` (patch `SpotifyClient` to raise if constructed).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `python -m pytest -q` → PASS.
- [ ] **Step 5: Commit** `git commit -m "Job de enriquecimento: tags separadas e BPM para o acervo"`

### Task 8: Discogs as a source (only if the gate passed)

Skip this task if Task 1 recorded a failed Discogs gate; note the skip in the spec's Gate results.

**Files:**
- Modify: `backend/app/db.py` (migration 4: `discogs_releases (album_key TEXT PRIMARY KEY, styles TEXT, fetched_at REAL NOT NULL)`)
- Modify: `backend/app/enrichment_store.py` (`get_release_styles(album_key) -> list[str] | None`, `put_release_styles(album_key, styles)`, 30-day TTL like tags)
- Modify: `backend/app/enrichment_job.py` (Task 7; `DISCOGS_ENABLED = True`; per album, not per track; ≤ 1 request/second)
- Test: `backend/tests/test_enrichment_job.py`

- [ ] **Step 1: Write failing tests:** `test_styles_fetched_once_per_album`, `test_no_token_skips_discogs`, `test_release_source_votes_in_blend` (styles `["Full-On"]` resolve via taxonomy → release votes full-on; add Discogs spellings found in Task 1 as aliases in the YAML).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `python -m pytest -q` → PASS.
- [ ] **Step 5: Commit** `git commit -m "Estilos do Discogs como fonte de evidência"`

### Task 9: Subgenre golden suite from external references

**Files:**
- Create: `backend/evals/subgenre_refs.yaml` (case list: id, artist, title, label, reference URL)
- Create: `backend/evals/congelar_subgeneros.py` (fetches and freezes inputs)
- Create: `backend/evals/subgenre_golden.yaml` (frozen cases + `limiares`)
- Create: `backend/evals/run_subgenre_evals.py`
- Modify: `backend/evals/genre_golden.yaml` (psy cases keep `genero`; their `subgenero` lines move out, kept only where a reference agrees, change noted in the file header)
- Modify: `.github/workflows/ci.yml` (run `python -m evals.run_subgenre_evals` after the genre evals)
- Modify: `backend/app/subgenre.py` (tuned constants)

**Interfaces:**
- Refs: ≥ 8 cases for each of progressive psytrance, full-on, offbeat, darkpsy, forest psy, goa trance, hitech, psychill; sources: the guide's example tracks (artist and title) and Beatport track pages looked up by hand (record the URL; no scraping).
- `congelar_subgeneros.py` (run with `docker compose exec backend python -m evals.congelar_subgeneros`): for each ref, fetch separated weighted Last.fm tags, Deezer bpm, Discogs styles (if enabled) and write `subgenre_golden.yaml` cases: `{id, faixa, referencia, subgenero, artista, faixa_tags, bpm, estilos}`.
- `run_subgenre_evals.py`: classifies each case with `taxonomy.classify` + `subgenre.blend`; prints confident-case accuracy, unsure rate, top-2 rate, per-subgenre table; `--verboso` shows evidence; exits 1 when confident accuracy < `limiares.precisao_confiante` or unsure rate > `limiares.max_incerto`.

- [ ] **Step 1: Write** `subgenre_refs.yaml` (≥ 64 refs) and the freeze script; **run** the freeze in Docker → `subgenre_golden.yaml` written.
- [ ] **Step 2: Write** the runner; **run** `python -m evals.run_subgenre_evals --verboso` → numbers print (no thresholds yet).
- [ ] **Step 3: Tune** `SOURCE_WEIGHTS`, `TEMPO_FALLOFF_BPM`, `UNSURE_MIN_SHARE` on the suite; keep `python -m pytest -q` green (Task 3 tests may need value updates, not rule changes).
- [ ] **Step 4: Set `limiares`** from this honest run (floor a few points under the result, ceiling a few points over the unsure rate); move psy `subgenero` lines out of `genre_golden.yaml`; **run** `python -m evals.run_genre_evals` and `python -m evals.run_subgenre_evals` → both "aprovado".
- [ ] **Step 5: Commit** `git commit -m "Conjunto dourado de subgênero com rótulos de referência externa"`

### Task 10: Subgenre API for the library page

**Files:**
- Create: `backend/app/subgenre_library.py`
- Modify: `backend/app/subgenres.py`
- Test: `backend/tests/test_subgenre_library.py`

**Interfaces:**
- `def library_subgenres(digests: dict[str, dict]) -> list[dict]` → `[{genre, name, bpm, about, source, confident, unsure}]` (track counts by lean, unique tracks) for every subgenre in `taxonomy.subgenres_of` of genres present.
- `def subgenre_tracks(digests: dict[str, dict], playlists: list[PlaylistSummary], name: str) -> dict` → `{info: {...}, confident: [track], leaning: [track]}`; track = `{id, name, artists, image, bpm, share, playlists: [{id, name}]}`, each list sorted by share desc; unique by track id.
- Routes: `GET /api/subgenres` → `library_subgenres`; `GET /api/subgenres/{name}` → `subgenre_tracks` (404 for an unknown name). Digests limited to the account's listing.

- [ ] **Step 1: Write failing tests:** `test_tracks_split_confident_and_leaning`, `test_unique_tracks_across_playlists`, `test_unknown_subgenre_404`, `test_only_account_playlists` (digest of a playlist not in the listing is excluded), `test_old_digest_without_fields_is_ignored_not_crash`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `python -m pytest -q` → PASS.
- [ ] **Step 5: Commit** `git commit -m "API de subgêneros do acervo"`

### Task 11: Playlist page uses the blend

**Files:**
- Modify: `frontend/src/pages/PlaylistDetail.jsx`
- Modify: `frontend/src/charts/GenreFlow.jsx` (prop `labelsOf`, default `(t) => t.genres`)
- Create: `frontend/src/components/SubgenreBars.jsx`
- Modify: `frontend/src/components/TrackTable.jsx` (prop `filter: { subgenre: string } | null`)

**Interfaces:**
- `SubgenreBars({ bars, total, onSelect, selected })`: one row per `SubgenreBar`, confident part solid, unsure part lighter (same hue, lower opacity), label links to `/subgenero/:name`, clicking the bar calls `onSelect(label)`. Falls back to `subgenre_distribution` when `subgenre_bars` is empty (old analyses).
- Single-genre playlists (`genre_distribution.length <= 1`) with ≥ 2 distinct `subgenre_lean` values render `GenreFlow` with `labelsOf={(t) => (t.subgenre_lean ? [t.subgenre_lean] : [])}` and a subgenre distribution built from the bars.
- Track table filtered to tracks whose `subgenre_lean` is the selected label, confident first then unsure, with a "Mostrando N faixas de X · limpar" line.

- [ ] **Step 1: Implement** the components and wiring (no frontend test runner exists; verification is the build plus the page).
- [ ] **Step 2: Run** `cd frontend && npm run build` → succeeds.
- [ ] **Step 3: Rebuild and check:** `docker compose up -d --build frontend`; confirm the bundle contains `SubgenreBars` strings (`docker compose exec frontend sh -c "grep -l 'subgenre_bars' /usr/share/nginx/html/assets/*.js"`); ask the owner to open a psy playlist (the browser pane can't sign in to Spotify).
- [ ] **Step 4: Commit** `git commit -m "Página da playlist: barras de subgênero com parte incerta e filtro"`

### Task 12: Track page "Por que este subgênero"

**Files:**
- Create: `frontend/src/components/SubgenreWhy.jsx`
- Modify: `frontend/src/pages/TrackDetail.jsx`
- Modify: `backend/app/models.py` and `backend/app/tracks.py`: add `subgenre_reference: dict | None = None` (`{name, bpm, source}` from `taxonomy.subgenre_info(lean)`) to `TrackDetail`, so the card needs no extra request.

**Interfaces:**
- `SubgenreWhy({ track })`: blend as one stacked bar (top 4 + "outros"); one line per `subgenre_evidence` entry; reference line "Full-on: 140–148 BPM, segundo psytranceguide.com", with the name linking to `/subgenero/:name` and the source to its URL; when `subgenre_unsure`, a line saying what's missing (no BPM / only artist tags / sources disagree), derived from which sources appear in the evidence. Renders nothing when `subgenre_blend` is empty.

- [ ] **Step 1: Implement.** **Step 2: Run** `npm run build` → succeeds; `python -m pytest -q` → PASS.
- [ ] **Step 3: Rebuild** frontend and backend containers; owner checks a track page.
- [ ] **Step 4: Commit** `git commit -m "Página da faixa explica o subgênero"`

### Task 13: Subgenre page and enrichment panel

**Files:**
- Create: `frontend/src/pages/Subgenre.jsx` (route `/subgenero/:name` in `App.jsx`, protected like the others)
- Create: `frontend/src/components/EnrichPanel.jsx`
- Modify: `frontend/src/api.js` (`getSubgenres`, `getSubgenre(name)`, `getEnrich`, `startEnrich`, `stopEnrich`)
- Modify: `frontend/src/pages/Profile.jsx` (a "Subgêneros" section listing `library_subgenres` with counts, linking to each page; `EnrichPanel` above it)

**Interfaces:**
- Subgenre page: header with name, our `about`, BPM range and source link; `EnrichPanel`; two lists "Classificadas como X" and "Tendem a X (incertas)" using the existing track row style (`SearchHit` or `cut-row`) with preview button, share, BPM and playlist chips.
- `EnrichPanel`: pending count and estimate, start button, progress while running (poll every 2.5 s like `Profile.jsx`), errors summary; hidden when nothing is pending.

- [ ] **Step 1: Implement.** **Step 2: Run** `npm run build` → succeeds.
- [ ] **Step 3: Rebuild** containers; owner runs the enrichment on their library and opens a subgenre page.
- [ ] **Step 4: Commit** `git commit -m "Página de subgênero e painel de enriquecimento"`

### Task 14: Docs and final verification

**Files:**
- Modify: `README.md` (new "Subgêneros" section: sources, unsure, enrichment job, evals; update the taxonomy section), `docs/CODEBASE_MAP.md`

- [ ] **Step 1: Update docs.**
- [ ] **Step 2: Run** `cd backend && python -m pytest -q && python -m evals.run_genre_evals && python -m evals.run_subgenre_evals` → all pass; `cd frontend && npm run build` → succeeds.
- [ ] **Step 3: Run against real data:** `docker compose up -d --build`, then `docker compose exec backend python -m scripts.reclassificar_generos` → report shows psy unsure rate and lean counts; share the numbers with the owner.
- [ ] **Step 4: Commit** `git commit -m "Documenta a evidência de subgênero"`
