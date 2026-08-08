# m3talist v2

## Problem

Cheap generic MP3/MP4 players (reference device: GENAI `yp3_2.0.43`) cannot browse
folders, so the library must be flattened into one directory. Flattening destroys
album order: these players read tracks in **FAT directory-entry order**, not
alphabetically and not by tag. The current script makes it worse — it wipes every
tag including `TRCK`, strips the leading track number from filenames, and writes
files from an unordered process pool.

The library is also opaque: no way to find duplicate rips, group by genre or era,
or see cover art, because tags are reduced to artist and album.

## Goal / Solution

Turn a folder of albums into a flat, device-safe collection where albums stay in
order and metadata is rich enough to browse.

**Ordering**, defended in four layers, cheapest first:

1. Global numeric filename prefix (`0042-time.mp3`) — aligns alphabetical order
   with write order.
2. Serialized final write, ordered by artist → album → disc → track. Transcoding
   stays parallel into a temp dir; only the move is sequential.
3. `TRCK` / `TPOS` preserved, for firmware that does read tags.
4. `fatsort -n` on the card, documented as an optional extra step.

**Device safety** is a stored profile, not a hardcoded assumption. Defaults follow
the compatibility consensus: ID3v2.3 + ID3v1 tail, UTF-16 text with BOM, `TYER`
instead of `TDRC`, ASCII-only filenames, CBR 128 kbps / 44.1 kHz / stereo. Cover
art ships **disabled**; a `calibrate` command writes a ladder of identical MP3s
with escalating cover sizes so the user finds their device's real limit once.

**Enrichment** is offline-first. The local SQLite catalog is the source of truth;
MusicBrainz and Cover Art Archive only fill gaps, and every response is cached.
No network means no enrichment — never a failure.

**Similarity** is metadata plus fingerprints, no signal analysis: Chromaprint
identifies duplicate rips of the same recording; genre and era grouping is SQL
over the catalog.

## Tech stack

| Concern | Choice | Note |
|---|---|---|
| Transcode / probe | `ffmpeg`, `ffprobe` via `subprocess` | replaces `pydub` — unmaintained, broken on Python 3.13 (`audioop` removed) |
| Tags | `mutagen` | `save(v1=2, v2_version=3)`; `delall()` per frame, never `delete()` |
| Cover resize | `Pillow` | forces baseline JPEG |
| Catalog + cache | `sqlite3` (stdlib) | |
| HTTP | `httpx` | MusicBrainz 1 req/s, mandatory User-Agent |
| Web UI | FastAPI + HTMX + SSE | no build step, no npm |
| Fingerprint | `fpcalc` (Chromaprint) | optional binary; absent means dedupe is skipped |

No task queue: a background thread over `multiprocessing.Pool` streaming progress
via SSE is enough for one local user. CLI and web UI are two adapters over one
core; the core knows neither.

## Data model

```
device_profile(name PK, id3_version, text_encoding, write_id3v1,
               cover_enabled, cover_max_px, bitrate, sample_rate,
               channels, max_files)

release(id PK, artist, title, year, mbid, cover_path,
        keep_order, needs_review)

track(id PK, release_id FK -> release.id,
      source_path UNIQUE, output_name,
      title, artist, album_artist, disc_no, track_no, year, genre,
      duration_ms, source_bitrate, source_sample_rate, source_channels,
      fingerprint, mbid, sort_index, status)

mb_cache(query_hash PK, response, fetched_at)
```

`sort_index` is the global write position — single source of truth for order,
computed once per run, reused by both the filename prefix and the move step.
`status`: `pending | copied | transcoded | failed`. `keep_order` marks a release
that must stay contiguous and in track order. `mb_cache` holds raw API responses
so a re-run is fully offline.

## Happy path

1. User drops `Pink Floyd - The Dark Side of the Moon/` into `input/`, opens the UI.
2. Scan reads tags via `mutagen` and stream info via `ffprobe`, creating one
   `release` and ten `track` rows. Track numbers come from `TRCK`, falling back to
   the filename prefix.
3. Enrichment matches the release on MusicBrainz, fills year and genre, pulls the
   front cover from Cover Art Archive. Everything lands in `mb_cache`.
4. Review screen shows the album in order. User confirms; `keep_order` stays set.
5. Build assigns `sort_index` library-wide. Source is FLAC, so `ffmpeg` transcodes
   to CBR 128 kbps / 44.1 kHz / stereo into a temp dir; tags are written as
   ID3v2.3 + ID3v1; cover is skipped unless calibration enabled it.
6. Files move into `output/` **sequentially by `sort_index`**, named
   `0042-speak-to-me.mp3` … `0051-eclipse.mp3`. SSE streams progress.
7. User copies `output/` to the card. Tracks play in order because filename order,
   tag order and FAT write order all agree.

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
whether it beats metadata for personal collections. The hook stays open:
`bliss-rs` or the frozen CC0 AcousticBrainz dump can fill `track` columns later
without touching the pipeline.
