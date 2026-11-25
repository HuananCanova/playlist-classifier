# Subgenre evidence: explainable subgenre classification

Date: 2026-11-25 · Status: draft for approval · Stage A of a two-stage plan (Stage B outlined at the end)

## Intent

The project exists to find out what subgenres a playlist or track is made of,
mostly inside electronic music and especially psytrance (progressive, full-on,
offbeat, darkpsy, forest…). "Psytrance" alone says almost nothing to the owner.

The owner does **not** trust their own ear as ground truth; the app is how they
want to learn. So the app must not hand down one label as fact. It should show
a **blend** of subgenres per track, say **why** (which evidence pointed where),
and say **"unsure"** when the evidence is thin or disagrees. The labels lean on
external references (a curated genre guide, community tags, release styles),
never on the owner's corrections.

Research backs this framing: even with 100 Beatport-labeled songs per class,
EDM subgenre classification reaches ~59% accuracy (Caparrini et al.), tempo is
the strongest single feature, and recent work moved to soft labels because many
tracks blend subgenres (Shu et al., 2024).

## What's wrong today (measured on the stored library, 352 psytrance tracks)

- 34% of psytrance tracks get no subgenre at all.
- Labels are effectively per artist: only 24 of 132 psy artists have tracks in
  more than one subgenre, because Last.fm rarely tags individual psy tracks and
  the artist's tags fill in.
- `goa trance` (59 tracks) is suspicious: on Last.fm `goa` is a loose catch-all.
- No track is `offbeat`; the taxonomy has no such entry, and `forest` is folded
  into `darkpsy`.
- 0 of 352 have a BPM: the account scan skips Deezer.
- The vocabulary is not the bottleneck: tags the taxonomy can't place are ~20,
  each used once.
- Fresh analyses (after the taxonomy change, in the Docker database) show the
  same pattern: in "Where My Mind Lives in 2026/7" 7 of 9 tracks are `goa
  trance`, in "Ritual Resonance" 9 of 9 are `progressive psytrance`, and **none
  of the 18 psy tracks has a Deezer BPM**, even though those playlists were
  opened with audio. Deezer's BPM coverage for psy may be far below the ~43%
  measured on mainstream tracks (see the BPM gate in section 3).

## Goals

1. Each track gets a subgenre **blend** (shares that sum to 1 over the subgenres
   of its winning genre), a top subgenre, a confidence, and per-source evidence.
2. A track is marked **unsure** instead of guessed when evidence is thin or the
   sources disagree.
3. Tempo becomes evidence: the track's BPM is compared with reference BPM ranges
   per subgenre.
4. Release-level styles from Discogs become evidence, **if** a sample check
   shows they carry useful psy distinctions (decision gate, below).
5. The psy vocabulary covers the subgenres in the reference guide (offbeat,
   forest, night full-on, psy-techno, suomi…), each with a BPM range, a short
   description written by us, and a source link.
6. Find songs by subgenre: inside a playlist (filter by a subgenre) and across
   the whole library (a page per subgenre).
7. The owner can learn from it: the track page explains each label in plain
   words, next to the reference range.
8. Accuracy is measurable against external references, not the owner's ear.
9. Stage B (audio comparison) can be added later as one more evidence source
   without reworking Stage A.

## Non-goals

- Owner corrections as ground truth (explicitly rejected: the owner is learning).
- Recommending tracks outside the owner's library.
- Audio analysis of any kind in Stage A (that is Stage B).
- Making non-electronic genres finer. The mechanism is generic, but only
  psytrance gets BPM ranges and new subgenres now.
- Bringing back Spotify popularity (removed from the API in Feb 2026).

## Anti-goals (would make this a failure even if it works)

- Confident labels on weak evidence. A wrong "full-on" shown as fact is worse
  than "unsure".
- A black box: any label the UI can't explain.
- Extra Spotify calls. The account was suspended once for request volume; none
  of this work may add Spotify traffic.
- Copying the reference guide's text or audio. We cite it and link to it;
  descriptions are our own words.

## Constraints

- **Spotify**: no audio features, no preview, no popularity. Rate limits are
  strict (see README "Limites do Spotify"). This feature uses only data already
  fetched from Spotify.
- **Deezer**: public, no key. BPM exists for ~43% of tracks (`0` = unknown);
  matching is by text search with validation (`deezer_client.py`). BPM coverage
  for psy specifically is unknown until fetched.
- **Last.fm**: track tags are sparse for psy; artist tags dominate.
- **Discogs**: free API, needs a personal access token; styles are set per
  release, not per track; exact psy style names must be checked on real releases.
- **Architecture**: `taxonomy.classify` is a pure function, tested by the golden
  set (`evals/genre_golden.yaml`) in CI. Keep classification pure: network
  lookups happen before, and their results are passed in.
- **Storage**: SQLite with versioned migrations (`db.py`); Last.fm/Deezer results
  cached 30 days per track. Stored analyses must be re-classifiable offline
  (as `scripts/reclassificar_generos.py` does today).
- **Deploy**: the owner runs Docker Compose (backend + nginx frontend). The
  database lives in the `data` volume, not in `backend/.data/` on the host.

## Approaches considered

- **A. Explainable evidence, no machine learning.** Combine tags (via the
  taxonomy), Deezer BPM against reference ranges, and Discogs styles into a
  blend with an explanation. Cheap, transparent, teaches. Limits: BPM ranges
  overlap (progressive vs offbeat), BPM is missing for many tracks, and tags
  stay coarse.
- **B. Compare audio to expert examples.** Fingerprint each track's 30s Deezer
  preview with an audio model (Essentia Discogs-EffNet) and compare with
  reference tracks labeled by experts. Hears the difference instead of trusting
  tags, and gives similar-by-sound. Costs: a heavy audio library in the backend
  image, building a reference set, AGPL license.
- **C. A first, designed so B plugs in as another evidence source.**

**Picked: C** (owner's choice). A fixes the per-artist labels and the missing
explanations soon; B adds "how it sounds" later without rework.

## Design (Stage A)

### 1. Taxonomy: psy vocabulary and reference ranges

Extend `taxonomy.yaml` so a subgenre can carry reference data. Proposed shape
(the builder may adjust the YAML layout, keeping it backward compatible):

```yaml
psytrance:
  aliases: [...]
  subgenres:
    full-on:
      aliases: [fullon]
      bpm: [140, 148]
      about: "Our own one-line description."
      source: https://psytranceguide.com
    forest psy:
      aliases: [forest, forest psytrance, forest darkpsy]
      bpm: [150, 160]
      ...
```

- Align the psytrance subgenres with the reference guide (psytranceguide.com,
  v1.2, 18 styles with BPM ranges). Add the missing ones, split `forest psy`
  from `darkpsy`, and keep existing entries working (aliases stay valid).
- The guide is one curated opinion, from 2017. Record the source per range so
  another reference can be added or swapped later.
- `goa trance`: keep it, but the bare tag `goa` should count less (or only with
  another psy signal), since it is used loosely. Builder's call on the
  mechanism; the golden set decides.
- Map the stray psy tags found in the library (`psyprog`, `psystyle`, …).

### 2. Evidence model

Classification becomes two steps:

1. **Genre** (unchanged): the existing tag vote picks the broad genre.
2. **Subgenre blend** within that genre: each evidence source returns a
   distribution over the genre's subgenres (or abstains), and the sources are
   combined by weight.

Sources in Stage A:

| Source | Input | What it says |
|---|---|---|
| `tags` | Last.fm track + artist tags through the taxonomy | today's subgenre votes, as a distribution |
| `tempo` | Deezer BPM | likelihood per subgenre from the reference ranges: full weight inside a range, falling off outside, shared where ranges overlap |
| `release` | Discogs styles of the track's release | distribution from styles that resolve in the taxonomy |

Output per track (new optional fields on the stored track, old analyses stay
valid):

- `subgenre_blend`: `[{label, share}]`, sorted, shares summing to 1
- `subgenre_lean`: the top label of the blend, always set when there is a blend
- `subgenre`: the top label when confident, null when unsure
- `subgenre_confidence`: 0–1
- `subgenre_unsure`: true when evidence is thin (e.g. one weak source) or the
  sources disagree (top labels differ, with comparable weight)
- `subgenre_evidence`: `[{source, says, detail}]`, e.g.
  `{source: "tempo", says: "full-on", detail: "146 BPM; full-on is 140–148"}`

Rules:

- A source with no data abstains; it does not pull the blend toward uniform.
- Source weights and the unsure thresholds live in one place (config or YAML)
  and are tuned against the golden set, not by feel.
- Artist-level tags must count less than track-level evidence (track tags,
  tempo), so tempo can separate two tracks by the same artist.
- The combination stays a pure function of its inputs (tags, BPM, styles), so
  CI can test it and stored analyses can be reclassified offline.
- Sources are pluggable: a source is "given a track's inputs, return a
  distribution or abstain, plus evidence lines". Stage B adds `audio` this way.

### 3. Enrichment job: BPM and separated tags for the library

Stored analyses can't feed the new model as they are: they keep tags merged
(`genres` / `subgenre_tags`, no weights, track and artist in one bag, as
`reclassify.py` notes), and the account scan skipped Deezer. The Last.fm cache
tables keep track and artist tags apart, but only for 30 days.

**Decision (our call):** one opt-in background "enrichment" job, per library
track, that fills what the evidence model needs:

- Last.fm track tags and artist tags, **kept separate and with weights**,
  stored with the track (not only in the 30-day cache), so later
  reclassification stays offline.
- Deezer BPM, for tracks without one.
- Discogs styles, if the Discogs gate passes (section 4).

No Spotify calls are involved: the track list comes from stored analyses and
summaries. Same UX pattern as the existing scan: show how many tracks and
roughly how long, run in the background with progress, survive leaving the
page, resume safely. Start with tracks whose genre has BPM ranges (psytrance);
the rest can follow. After it runs, reclassify stored data offline.

Analyses made after this change store separated, weighted tags directly, so
new analyses don't need the job.

**BPM gate (first task, alongside the Discogs gate):** fetch Deezer for ~50
of the owner's psy tracks and report how many get a BPM. If coverage is very
low, the tempo source stays in the design (it's cheap) but the expectations
change: most psy tracks will be "unsure" until Stage B's audio tempo model, and
Stage B moves up in priority. Report the number before tuning anything.

### 4. Discogs (behind a decision gate)

- New client, token in `backend/.env` (`DISCOGS_TOKEN`); without a token the
  source abstains and nothing else changes.
- Lookup by artist + album (Spotify album name, already stored), cached per
  album in SQLite for 30 days, respecting Discogs rate limits.
- **Gate (first implementation task):** look up ~30 of the owner's psy albums
  and report which styles come back. If the styles don't separate psy
  subgenres beyond "Psy-Trance / Goa Trance / Progressive Trance", drop the
  source and record why. Don't build the UI around it before this.

### 5. Interface

- **Unsure tracks still count, marked as unsure (our call).** Many psy tracks
  will be unsure at first; hiding them would empty the pages this feature is
  for. Every track keeps its blend and its leading label (`subgenre_lean`, the
  top of the blend, set even when unsure); `subgenre` stays null when unsure.
  Pages query the blend/lean, not only `subgenre`.
- **Playlist page, subgenre chart**: built from the blends (sum of shares over
  tracks). Each bar shows the confident part solid and the unsure part
  lighter, so "how much of this is a guess" is visible per subgenre. Clicking a
  subgenre filters the track table to the tracks it leads, confident first,
  then "leans toward" ones.
- **Playlist page, single-genre playlists**: the genre path chart is already
  hidden when there is one genre. Show the same path chart at the subgenre
  level instead, when there are at least two subgenres. (Our call; it's the
  view the project was started for.)
- **Track page, "Why this subgenre"**: the blend as a bar, one plain line per
  evidence source, and the reference: "Full-on: 140–148 BPM, per
  psytranceguide.com". When unsure, say what's missing ("no BPM, and Last.fm
  only tags the artist").
- **Subgenre page** (`/subgenero/:name`): our description, BPM range and source
  link, then the library's tracks in two groups: "Classified as X" (confident)
  and "Leans toward X" (unsure), each sorted by share, with preview and the
  playlists it's in. Listening to the "leans toward" group is part of how the
  owner learns. This is "find songs that match the
  subgenre" across the library. Reachable from the playlist chart, the track
  page and the profile.
- **Search page**: unchanged in Stage A. The search text could include the top
  subgenre later; out of scope here.

### 6. Measuring accuracy

The existing `evals/genre_golden.yaml` has psy subgenre cases labeled by human
judgment, mostly with artist tags only, and CI fails below a 0.75 subgenre
threshold. Under the new rules many of those cases should rightly become
"unsure", so the suite changes (our calls):

- **Genre cases stay as they are**, with the same genre threshold. Broad genre
  is not what's being changed.
- **Psy subgenre cases move to a new suite** (`evals/subgenre_golden.yaml`).
  An old case is kept only if an external reference agrees with its label;
  otherwise it's dropped or relabeled from the reference, and the change is
  recorded in the file.
- **Where reference labels come from:**
  - the guide's example tracks (4 per style; artist and title only, we don't
    store their audio);
  - Beatport's genre/subgenre shown on the track's public page, looked up by
    hand while building the suite (no scraping), with the URL recorded per case.
- **Size:** at least 8 cases for each of the main psy subgenres (progressive,
  full-on, offbeat, darkpsy, forest, goa, hitech, psychill), about 64+ cases.
  Below that, tuning weights on the suite is noise. The other guide styles can
  have fewer cases and are reported but not gated.
- **Inputs per case are frozen** (separated weighted tags, BPM, Discogs
  styles), fetched once by a script using the app's existing keys from
  `backend/.env`. Calling Last.fm/Deezer/Discogs for tracks outside the
  library is fine: no Spotify involved.
- **Scoring:** accuracy on the confident cases, unsure rate, and how often the
  reference label is in the blend's top 2. "Unsure" is never a hit.
- **CI gate:** confident-case accuracy above a floor and unsure rate below a
  ceiling, both set from the first honest run (not picked in advance).
- Expect modest numbers; the goal is honest labels, not 90%.

## Gate results (2026-11-25)

- **BPM gate:** `scripts/medir_fontes_psy` on the local library copy (354 distinct
  psy tracks), first 150 tracks: Deezer found 80 of 150, and only **12 of 150
  (8%) have a BPM**. A first run on 50 gave 8/50 (16%). Values seen: 97.5–152.
  Per the rule in section 3: the tempo source stays (it's cheap), but most psy
  tracks will be "unsure" from tempo's point of view until Stage B's audio
  tempo model; Stage B moves up in priority.
- **Discogs gate: failed.** Only 5 albums had a stored name (5/5 found: Psy-Trance
  5, Progressive Trance 4). A wider read-only check over the releases of the 40
  most frequent psy artists in the library (up to 25 releases each) returned
  Psy-Trance 511, Progressive Trance 498, Goa Trance 20 as the psy styles —
  nothing finer. Klipsun (darkpsy) comes back as Psy-Trance / Progressive
  Trance. Discogs styles don't separate psy subgenres beyond the three named in
  section 4, so the `release` source is dropped: Task 8 is skipped and
  `DISCOGS_ENABLED` stays False. The client and token stay, unused, in case a
  later reference needs them.
- **Subgenre eval suite: 35 cases, none of the 8 main subgenres reaches the 8
  per class asked in section 6** (4–6 each). The guide gives only 4 examples per
  style, Beatport pages mostly say just "Psy-Trance", Beatport has no offbeat or
  psychill and merges darkpsy+forest and hitech+psycore, and ambiguous pages
  were left out rather than filling the quota by guesswork
  (`evals/subgenre_refs.yaml`). So weights and thresholds stay untuned initial
  values; the suite gates regressions, it does not calibrate.

## Stage B (later, its own spec)

- Fetch 30s Deezer previews server-side, compute an audio embedding
  (Essentia Discogs-EffNet, in the backend Docker image), store the vectors.
- Reference set: tracks with expert labels (the guide's examples, tracks with
  a Beatport subgenre), embedded the same way.
- New `audio` evidence source: nearest reference tracks → "sounds closest to
  these full-on references". The same embeddings give similar-by-sound tracks.
- An audio tempo model (Essentia TempoCNN) could fill the ~57% of tracks with no
  Deezer BPM. Browser-side BPM detection was tried and removed (60% accuracy);
  this would need to beat that on the golden set.
- Open questions for that spec: image size, CPU time per track, AGPL license,
  how preview URLs (signed and expiring) are fetched in bulk.

## Left to the builder

- YAML layout details, the tempo falloff curve, source weights and thresholds
  (tuned on the golden set).
- Exact field names, the migration, and how the reclassify script picks up
  BPM and styles.
- Chart and page layout, within the existing hand-made chart kit and palette.
- Order of work, except that the BPM and Discogs gates come first, and the
  Discogs gate comes before any Discogs UI.

## Calls made while writing this (for the owner to check)

1. One enrichment job re-fetches Last.fm tags (separated, weighted) together
   with BPM, instead of accepting merged stored tags.
2. BPM gate: measure Deezer's BPM coverage on psy before relying on tempo.
3. Unsure tracks still appear, as "leans toward", on the playlist filter and
   the subgenre page, and their share shows lighter in the bars.
4. Genre golden cases stay; psy subgenre cases move to a new suite labeled from
   external references (guide examples, Beatport pages looked up by hand),
   at least 8 per main subgenre.
5. Single-genre playlists show the path chart at the subgenre level.
6. Spec written in English, while the README and code comments are Portuguese.

## Sources

- psytranceguide.com (v1.2): 18 psy styles, BPM ranges, example tracks
- Caparrini et al., EDM subgenre classification on Beatport (59% with 23 classes)
- Hsu, Chen & Yang 2021, arXiv 2110.08862 (tempograms improve EDM subgenre CNNs)
- Shu et al. 2024, arXiv 2409.06690 (soft labels for blended subgenres)
- Essentia models, Discogs-EffNet (400 Discogs styles), essentia.upf.edu/models.html
- Spotify Web API changelog, Feb 2026 (popularity removed)
