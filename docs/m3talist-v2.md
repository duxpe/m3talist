# m3talist v2

## Problem

Cheap generic MP3/MP4 players cannot browse folders, so the library must be
flattened into one directory. Flattening destroys album order: these players read
tracks in **FAT directory-entry order**, not alphabetically and not by tag. The
current script makes it worse — it wipes every tag including `TRCK`, strips the
leading track number from filenames, and writes files from an unordered process
pool.

The library is also opaque: no way to find duplicate rips, group by genre or era,
or see cover art, because tags are reduced to artist and album.

Reference hardware is a Smartlink SL680x reporting firmware `yp3_2.0.43`, ~523
tracks. Its ID3 behaviour is undocumented — no public SDK exists. See
[device-sl680x](./device-sl680x.md) for identification and what that rules out.

## Goal / Solution

Turn a folder of albums into a flat, device-safe collection where albums stay in
order and metadata is rich enough to browse.

**Ordering**, defended in four layers, cheapest first:

1. Global numeric filename prefix (`0042-time.mp3`) — aligns alphabetical order
   with write order.
2. Serialized final write by artist → album → disc → track, `sync` after each file
   so writeback cannot reorder directory entries. Transcoding stays parallel into
   a temp dir; only the move is sequential.
3. `TRCK` / `TPOS` preserved, for firmware that does read tags.
4. `fatsort -n` on the card, documented as an optional extra step.

**Device safety** is one fixed conservative output format: ID3v2.3 + ID3v1 tail,
UTF-16 with BOM, `TYER` over `TDRC`, ASCII filenames, CBR 128 kbps / 44.1 kHz /
stereo. None of it is verified for this chip, and none of it needs to be — where
the safe option costs nothing, it wins without an experiment.

Cover art is the exception: unknown limit, and "off" is a loss rather than a cost.
`calibrate` writes a ladder of identical MP3s with escalating cover sizes; the
user plays them and the last size that worked becomes `cover_max_px`. One run,
one config line, permanent. It is the only thing the tool measures.

**Enrichment** is offline-first. The SQLite catalog is the source of truth;
MusicBrainz and Cover Art Archive only fill gaps, every response cached. No
network means no enrichment — never a failure.

**Similarity** is metadata plus fingerprints, no signal analysis: Chromaprint
finds duplicate rips of the same recording; genre and era grouping is SQL.

## Tech stack

| Concern | Choice | Note |
|---|---|---|
| Transcode / probe | `ffmpeg`, `ffprobe` via `subprocess` | replaces `pydub` — unmaintained, broken on Python 3.13 (`audioop` removed) |
| Tags | `mutagen` | `save(v1=2, v2_version=3)`; `delall()` per frame, never `delete()` |
| Cover resize | `Pillow` | forces baseline JPEG |
| Catalog + cache | `sqlite3` (stdlib) | |
| HTTP | `httpx` | MusicBrainz 1 req/s, mandatory User-Agent |
| Web UI | FastAPI + Jinja2 + SSE | no build step, no npm, no runtime asset fetched |
| Fingerprint | `fpcalc` (Chromaprint) | optional binary; absent means dedupe is skipped |

No task queue: a background thread over `multiprocessing.Pool` streaming progress
via SSE is enough for one local user. CLI and web UI are two adapters over one
core; the core knows neither.

## Data model

Output format is a constant in code, not data — there is one device. The only
measured value, `cover_max_px`, lives in a config file next to the input path.
SQLite holds what is actually per-item:

```
release(id PK, artist, title, year, mbid, cover_path, needs_review)

track(id PK, release_id FK -> release.id,
      source_path UNIQUE, output_name,
      title, artist, album_artist, disc_no, track_no, year, genre,
      duration_ms, source_bitrate, source_sample_rate, source_channels,
      fingerprint, mbid, sort_index, status)

mb_cache(query_hash PK, response, fetched_at)
```

`sort_index` is the global write position — single source of truth for order,
computed once per run, reused by both the filename prefix and the move step.
`status`: `pending | copied | transcoded | failed`. `mb_cache` makes a re-run
fully offline.

## Happy path

1. User drops `Pink Floyd - The Dark Side of the Moon/` into `input/`, opens the UI.
2. Scan reads tags via `mutagen` and stream info via `ffprobe` into one `release`
   and ten `track` rows. Track numbers come from `TRCK`, else the filename prefix.
3. Enrichment matches the release on MusicBrainz, fills year and genre, pulls the
   cover from Cover Art Archive. Everything lands in `mb_cache`.
4. Review screen shows the album in order. Nothing to correct, so the user moves on.
5. Build assigns `sort_index` library-wide. Source is FLAC, so `ffmpeg` transcodes
   into a temp dir; tags written in the fixed device-safe format.
6. Files move into `output/` **sequentially by `sort_index`**, `sync` after each,
   named `0042-speak-to-me.mp3` … `0051-eclipse.mp3`. SSE streams progress.
7. User copies `output/` to the card sequentially. Tracks play in order because
   filename order, tag order and FAT write order all agree.

## Edge case

An album arrives with no `TRCK`, no numeric filename prefix, and no network —
order cannot be derived from anything trustworthy.

Scan sets `release.needs_review = 1` and assigns no `sort_index`. Build skips that
release and reports it; everything else completes. The UI lists it in
filename-alphabetical order as a guess and the user drags tracks into place. The
chosen order persists, so the next run needs neither network nor a second
decision. `--force-alpha` accepts the guess unattended, for scripting.

## Out of scope

Signal analysis (BPM, key, mood) — slow, and the community is still split on
whether it beats metadata for personal collections. `bliss-rs` or the frozen CC0
AcousticBrainz dump can fill `track` columns later without touching the pipeline.
