# Implementation plan — m3talist v2

Executes [m3talist-v2](./m3talist-v2.md) against the current codebase. Hardware
context in [device-sl680x](./device-sl680x.md).

Branch: `feature/m3talist-v2`, cut from `main` after the discovery docs merged.

## Ground rules

- Smallest thing that works. No layer, interface or abstraction without a
  concrete need already present in this repo.
- Code, identifiers and comments in English. Comments only where the code cannot
  speak for itself.
- Tests written after the code, per phase. One or two e2e over the happy path,
  targeted unit tests only where the logic is tricky (ordering, naming, tags).

## How to execute this plan

Phases run in order, 1 through 7. Each phase is one logical unit of work and one
commit. Do not start a phase before the previous one is green.

Per phase:

1. Implement it.
2. Run the tests. They pass before anything else happens.
3. Hand the diff to `duxpe-code:code-reviewer` for a fresh-context pass. Fix
   blocking findings; note the rest.
4. Report to the user what landed and what the review said, then **ask before
   committing**. No git operation — commit, push, branch, PR — happens without
   explicit permission.

Phase 1 alone fixes the reported bug. Stopping after any phase leaves a working
tool, which is why they are ordered this way.

## What is being replaced

| Current | Fate |
|---|---|
| `src/app.py` `prepare_audio` | split into `audio.py` + `tags.py` + `pipeline.py` |
| `src/app.py` `imap_unordered` | parallel transcode kept, **move serialized** |
| `src/metadata.py` if-chain | dict lookup, ~90 lines to ~15 |
| `src/metadata.py` `clear_metadata` | `delall()` per frame; never `delete()` |
| `src/utils.py` `lstrip(digits)` | track number becomes the prefix, not garbage |
| `pydub` | `ffmpeg`/`ffprobe` via `subprocess` |
| `run.py` | `python -m m3talist <command>` |

Package renames `src/` → `m3talist/` so the module path matches the project. Do
this first, as its own step, so the rename does not hide behind logic changes.

## Architecture

Dependencies point inward. `pipeline` orchestrates; nothing imports `web` or `cli`.

```
m3talist/
  models.py       Track, Release, BuildResult dataclasses
  profile.py      device-safe output constants + cover_max_px from config
  naming.py       ASCII slug, numeric prefix
  ordering.py     sort_index assignment, needs_review detection
  catalog.py      SQLite schema, queries
  audio.py        ffprobe probe, ffmpeg transcode, passthrough decision
  tags.py         mutagen ID3v2.3 + ID3v1 read/write
  artwork.py      fetch, resize to baseline JPEG, embed
  enrich.py       MusicBrainz + Cover Art Archive, rate-limited, cached
  fingerprint.py  fpcalc wrapper, duplicate grouping
  pipeline.py     scan / build / calibrate use cases
  cli.py          argparse subcommands
  web/
    app.py        FastAPI routes, SSE
    templates/    Jinja2 partials for HTMX
    static/       one CSS file, no JS build
```

## Data model

```sql
CREATE TABLE release (
  id INTEGER PRIMARY KEY, artist TEXT, title TEXT, year INTEGER,
  mbid TEXT, cover_path TEXT,
  keep_order INTEGER DEFAULT 1, needs_review INTEGER DEFAULT 0);

CREATE TABLE track (
  id INTEGER PRIMARY KEY, release_id INTEGER REFERENCES release(id),
  source_path TEXT UNIQUE NOT NULL, output_name TEXT,
  title TEXT, artist TEXT, album_artist TEXT,
  disc_no INTEGER, track_no INTEGER, year INTEGER, genre TEXT,
  duration_ms INTEGER,
  source_codec TEXT, source_bitrate INTEGER,
  source_sample_rate INTEGER, source_channels INTEGER,
  fingerprint TEXT, mbid TEXT,
  sort_index INTEGER, status TEXT DEFAULT 'pending');

CREATE TABLE mb_cache (
  query_hash TEXT PRIMARY KEY, response TEXT, fetched_at TEXT);
```

Output format lives in `profile.py` as constants — one device, no table.
`cover_max_px` is the single measured value, stored in `config.toml`.

## Phases

Each phase is independently useful and separately reviewable.

### Phase 1 — ordering (the actual bug)

Fixes Dark Side of the Moon on its own; everything later is enrichment.

`models.py`, `naming.py`, `ordering.py`, `catalog.py`, `tags.py`, minimal
`pipeline.scan` + `pipeline.build`, `cli.py`.

- `naming.slug()` — ASCII, lowercase, hyphenated, **keeps** the track number as a
  zero-padded prefix instead of stripping it.
- `ordering.assign()` — sorts by artist → album → disc → track, writes a global
  `sort_index`. Missing track order with no fallback sets `needs_review` and
  assigns nothing.
- `tags.write()` — `delall()` for the frames being replaced, then
  `save(v1=2, v2_version=3)`. `TRCK` as `n/total`, `TPOS` when multi-disc, `TYER`
  not `TDRC`, UTF-16 text.
- `pipeline.build()` — transcode in parallel to a temp dir, then move into
  `output/` **sequentially by `sort_index` with `os.fsync` per file**.

**Done when** a folder with shuffled filenames and intact `TRCK` produces
`0001-…` … `000N-…` in album order, and the on-disk directory entry order matches.

### Phase 2 — audio

`audio.py`. `ffprobe -print_format json -show_streams` reads codec, bitrate,
sample rate, channels. If the source is already MP3 CBR 128k / 44.1 kHz / stereo,
copy the file instead of re-encoding. Otherwise
`ffmpeg -c:a libmp3lame -b:a 128k -ar 44100 -ac 2`.

Missing `ffmpeg` fails loudly at startup with an install hint, not mid-run.

### Phase 3 — enrichment

`enrich.py`. `httpx` against MusicBrainz (1 req/s, real User-Agent) and Cover Art
Archive. Every response cached in `mb_cache` keyed by query hash. All network
calls wrapped so any failure degrades to "not enriched" — never an error.
`--offline` skips the network entirely.

### Phase 4 — artwork and calibrate

`artwork.py` resizes to `cover_max_px` as **baseline** JPEG (`progressive=False`)
and embeds `APIC` type 3. Disabled until calibrated.

`pipeline.calibrate()` writes six identical MP3s to `output/_calibrate/`: no
cover, 100, 200, 300, 500 px baseline, plus one progressive. The user plays them
and records the last good size.

### Phase 5 — similarity

`fingerprint.py` shells out to `fpcalc`, stores fingerprints, groups exact
duplicates. Genre and era grouping is plain SQL over `track`. Absent `fpcalc`
disables dedupe with a notice — never a hard failure.

### Phase 6 — web UI

See the design section below.

### Phase 7 — tests and docs

`pytest`. Two e2e runs over a fixture library (happy path, `needs_review` edge),
unit tests for `naming`, `ordering` and `tags`. Rewrite `readme.md` for the new
entry point.

## UI design

Eighties phosphor terminal, but a real application — the theme never costs
usability.

### Tokens

```
--bg        #080b08     near-black, faint green cast
--panel     #0c110c
--fg        #33ff66     phosphor green
--dim       #1f9944     secondary text, frame IDs
--amber     #ffb000     needs_review, warnings
--cyan      #38f0ff     selection, focus, links
--magenta   #ff4fd8     accent, used sparingly
--red       #ff3b3b     errors
```

System monospace stack only — no webfonts, nothing fetched at runtime.
Phosphor bloom via `text-shadow`, scanlines via a `repeating-linear-gradient`
overlay, plus a soft vignette. All of it behind a `CRT: ON/OFF` toggle in the
status bar and off automatically under `prefers-reduced-motion`.

### Layout

Three regions, matching the reference terminal:

- **Top bar** — inverted (green fill, dark text): `M3TALIST // LIBRARY` on the
  left; track count, `ONLINE`/`OFFLINE`, and the CRT toggle on the right.
- **Left rail** — boxed items: `LIBRARY`, `BUILD`, `DUPES`, `CALIBRATE`, `CONFIG`.
- **Content** — boxed panels drawn with CSS borders and corner glyphs.
- **Bottom bar** — live key hints: `↑↓ select · ENTER open · / filter · ? help`.

The `readme.md` block-glyph logo becomes the masthead on the index.

### Screens

1. **LIBRARY** — releases as a dense table. `needs_review` rows in amber with a
   `⚠ ORDER` marker. Filter with `/`.
2. **RELEASE** — track list showing the prefix that will be written
   (`0042-time.mp3`). Reorder with `[` and `]`, or drag. Confirm clears
   `needs_review`.
3. **BUILD** — Dwarf-Fortress-style streaming log on the left, ASCII progress bar
   `[████████░░░░░░] 47%` and `QUEUED / DONE / FAILED` counters on the right. Fed
   by SSE.
4. **DUPES** — fingerprint groups, keep one, drop the rest.
5. **CALIBRATE** — generates the ladder, then a form to record the last good size.
6. **CONFIG** — paths, `cover_max_px`, offline switch.

### Metadata as texture

The theme carries real information instead of decoration: every field is labelled
with its ID3 frame in dim text — `ARTIST · TPE1`, `ALBUM · TALB`,
`TRACK · TRCK` — so the screen teaches the format it writes.

### Keyboard

`↑↓`/`j k` move · `Enter` open · `Esc` back · `g`/`G` top/bottom · `/` filter ·
`[` `]` reorder · `s` scan · `b` build · `?` help overlay.

Every action is also clickable. Keyboard is the fast path, not the only path.

## Dependencies

Added: `httpx`, `Pillow`, `fastapi`, `uvicorn`, `jinja2`, `pytest`.
Kept: `mutagen`, `rich`. Removed: `pydub`.
External binaries: `ffmpeg`, `ffprobe` (required), `fpcalc` (optional).

## Settled decisions

Agreed before implementation started. Not open for reinterpretation mid-build.

1. **Package rename confirmed.** `src/` → `m3talist/`, all imports rewritten in a
   single commit at the start of Phase 1. Entry point becomes
   `python -m m3talist <command>`.
2. **`input/` is one album per subfolder.** Nested trees (`Artist/Album/`) are out
   of scope. A subfolder containing only subfolders is reported and skipped, not
   walked.
3. **Build always rewrites `output/` in full.** Incremental rebuild would write
   files out of `sort_index` sequence and break the FAT write-order guarantee,
   which is the whole point. `output/` is cleared at the start of a build. At 523
   tracks this costs a few minutes and buys a guarantee.
