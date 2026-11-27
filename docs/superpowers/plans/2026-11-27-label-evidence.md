# Record Label Evidence — Implementation Plan

Spec: `docs/superpowers/specs/2026-11-25-subgenre-evidence-design.md`, section
"Record label evidence". Already on master: `app/labels.yaml` (63 labels from
psytranceguide.com), `app/labels.py` (`lookup`, `label_source` — pure),
`subgenre.SOURCE_WEIGHTS["label"] = 0.7`, `SOURCES_THAT_NEED_COMPANY`,
`deezer_client.get_track_label`, `scripts/medir_selos_psy.py`.

What is missing is the plumbing: nothing stores a track's label, nothing
fetches it for the library, nothing passes it to `subgenre.blend`, and neither
the track page nor the AI chat can show it.

## Global constraints

- **Zero extra Spotify calls.** Labels come from Deezer only.
- **Classification stays pure.** Network lookups happen before; `labels.label_source`
  results are passed into `subgenre.blend(extra=...)`. No import of `labels`
  from `subgenre` (cycle: `labels` imports `subgenre`).
- **Failure is not data.** `get_track_label` → `None` (failure) is never
  stored; `""` (album has no label) is stored with a checked-at time.
- **New playlist analyses don't fetch labels** (2 Deezer calls per track would
  slow every analysis). They use a label already stored. The library
  enrichment job and the single-track page fetch them.
- **Labels are cached per Deezer album** in SQLite with no TTL (a release's
  label doesn't change): one album fetch serves every track on it.
- Code comments, identifiers and user-facing text follow the repo's existing
  Portuguese style. Tests: `cd backend && python -m pytest -q` (needs
  `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `LASTFM_API_KEY` set to any value
  when there's no `backend/.env`). Frontend: `cd frontend && npm run build`.
- TDD: failing test first, then the code, then the whole suite green.

## Task L1 — Storage: label per track, cached per album

Files: `app/db.py` (new migration), `app/evidence_store.py`,
`app/deezer_client.py`, `app/enrichment_store.py` (album cache helpers),
`tests/test_evidence_store.py`, `tests/test_deezer_label.py`.

- Migration (append to `MIGRATIONS`, never edit old ones):
  `ALTER TABLE track_evidence ADD COLUMN label TEXT;`
  `ALTER TABLE track_evidence ADD COLUMN label_checked_at REAL;`
  `CREATE TABLE deezer_album_labels (album_id INTEGER PRIMARY KEY, label TEXT NOT NULL, fetched_at REAL NOT NULL);`
- `TrackEvidence` gains `label: str | None = None` and
  `label_checked_at: float | None = None`; `_from_row` / `put` handle them with
  the same "None never erases" merge.
- `missing()`: a row with `deezer_id` set and `label_checked_at` None is
  missing (the label can only be asked once the Deezer match exists).
- `deezer_client.get_label_for_track(client, deezer_id) -> str | None`: fetch
  the track detail for the album id, read the album label from
  `deezer_album_labels` if present, otherwise fetch `/album/{id}` and store it
  (only on success; `""` is a success). Keep `get_track_label` working (the
  measurement script uses it) — it may delegate.
- Tests: roundtrip with label; `put` without label keeps stored label;
  `missing` includes matched-but-unlabelled rows and excludes rows with
  `deezer_id` None; album cache hit makes no `/album` request; failure is not
  cached.

## Task L2 — Enrichment job fetches labels

Files: `app/enrichment_job.py`, `tests/test_enrichment_job.py`.

- In `_lote`, after the Deezer step: for each track whose (stored or just
  found) `deezer_id` is set and whose `label_checked_at` is None, call
  `deezer_client.get_label_for_track` (concurrency limited like Deezer:
  `DEEZER_CONCURRENCY`). `None` → `progress.error(f"{name}: selo (Deezer)")`,
  nothing stored; a string → `label` + `label_checked_at`.
- Update the module docstring and `TRACKS_PER_MINUTE` comment (labels cost up
  to two more calls per track, fewer with the album cache).
- Tests: job fills label; failed label lookup retried next run; track with
  stored `deezer_id` but no label gets only the label call (no Last.fm/Deezer
  search); `test_no_spotify_calls` still holds.

## Task L3 — Classification uses the label everywhere

Files: `app/labels.py`, `app/genre_analysis.py`, `app/reclassify.py`,
`app/tracks.py`, tests (`test_reclassify_subgenre.py`,
`test_genre_analysis_subgenre.py`, a track-detail test).

- `labels.blend_with_label(genre, *, artist_tags, track_tags, bpm, label)`:
  `subgenre.blend(..., extra=[s] if (s := label_source(genre, label)) else [])`.
- Use it in: `genre_analysis` new analysis (label from stored evidence) and
  `_add_audio` (via `reclassify.subgenre_of`), `reclassify._blend` /
  `subgenre_of` (label from `TrackEvidence`), `tracks.py` track detail.
- Track page: when the stored evidence has a `deezer_id` but no
  `label_checked_at`, fetch the label for that one track
  (`get_label_for_track`) and store it, like the page already does for BPM.
- `TrackDetail` gains `label: str | None` and `label_info: LabelRef | None`
  (`name`, `nota`, `fonte`, `shares: list[SubgenreShare]`) when the label is in
  the map — the UI and the chat use it.
- Tests: reclassify with a mapped label and track tags agreeing → confident;
  label alone → unsure with that lean; unknown label → identical result to no
  label; track detail exposes `label_info`.

## Task L4 — Golden set measures the label

Files: `evals/congelar_subgeneros.py`, `evals/run_subgenre_evals.py`,
`evals/subgenre_golden.yaml` (regenerated, not hand-edited), `tests/` if the
eval runner has tests.

- Each frozen case gains `selo` (string; `""` = no label; `null` = not
  captured / lookup failed).
- `congelar_subgeneros.py --so-selo`: fills only `selo` for existing cases via
  Deezer, keeping tags and BPM as frozen (Last.fm may be unreachable). Prior
  `selo` is kept on failure, as the script already does for other fields.
- `run_subgenre_evals.py` passes `extra=[labels.label_source(genre, selo)]`.
- Run it, record the numbers (confident precision, unsure rate, top-2) in the
  `limiares` comment and the spec. Adjust `max_incerto` / `precisao_confiante`
  only as the existing comment's rules say. Report honestly, including misses.

## Task L5 — "Why this label" card shows the label

Files: `frontend/src/components/SubgenreWhy.jsx` (and the track page if it
passes props), `frontend/src/api` types if any.

- `FONTES.label = "Selo (Deezer)"`.
- In the "why unsure" hints: when no `label` evidence, add "selo fora do mapa
  ou desconhecido" only if the track has a label; "sem selo conhecido" if not.
- Under the evidence list, when `label_info` exists: label name, our note, and
  a link to its source (same pattern as the subgenre reference link).
- `npm run build` passes.

## Task L6 — AI chat explains the label

Files: `app/ai_tools.py`, tests for it (create `tests/test_ai_tools.py` if
none).

- `analisar_faixa_json` adds `"selo": {"nome", "no_mapa", "subgeneros"
  (shares), "nota", "fonte"}` (or `null`), plus the subgenre result
  (`subgenero`, `inclinacao`, `incerto`, `evidencia` lines) if not already
  there.
- `system_prompt`: one short paragraph — the label describes the release's
  catalogue, not the track; say so when it's the only evidence; cite the
  source link; never invent a label's style when `no_mapa` is false.
- Tests on the JSON shape with a mocked `build_track_detail`.

## Task L7 — Docs and final review

- README section on subgenre evidence: label source, the enrichment job now
  fetches labels, how to add a label to `labels.yaml` (needs a source).
- Spec: mark the label section as built, with the golden numbers from L4.
- Whole suite, frontend build, and a code review of the full diff.
