    ▖  ▖▄▖▄▖▄▖▖ ▄▖▄▖▄▖
    ▛▖▞▌▄▌▐ ▌▌▌ ▐ ▚ ▐
    ▌▝ ▌▄▌▐ ▛▌▙▖▟▖▄▌▐

Turns a music library into one flat folder that cheap MP3/MP4 players can actually
play in the right order.

Those players cannot browse folders, so everything has to be flattened — and once
flattened, album order falls apart. They read tracks in **FAT directory-entry
order**, which is creation order: not alphabetical, not by tag. m3talist defends
the order in four layers at once: a global numeric filename prefix, a strictly
sequential write, preserved `TRCK`/`TPOS` tags, and `fatsort` as an optional last
resort.

Everything it writes is deliberately conservative — ID3v2.3 with an ID3v1 tail,
UTF-16 text, `TYER` instead of `TDRC`, CBR 128 kbps — because the reference device
(a Smartlink SL6801) has no public documentation for its ID3 parser. See
[docs/device-sl680x.md](docs/device-sl680x.md).

## Install

Python 3.11 or newer, plus two external tools:

| Tool | Needed for | Required |
|---|---|---|
| `ffmpeg` / `ffprobe` | transcoding and reading stream info | yes |
| `fpcalc` (chromaprint) | duplicate detection | no — the feature just stays off |

```bash
make deps      # install ffmpeg and fpcalc for your platform
make install   # create .venv and install m3talist
make doctor    # report what is present and what is missing
```

`make help` lists every target. If you would rather not use make:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

### External tools by platform

| Platform | ffmpeg | fpcalc |
|---|---|---|
| Fedora | `sudo dnf install ffmpeg-free` <br>(or `ffmpeg` from RPM Fusion) | `sudo dnf install chromaprint-tools` |
| Debian · Ubuntu · Mint | `sudo apt install ffmpeg` | `sudo apt install libchromaprint-tools` |
| Arch | `sudo pacman -S ffmpeg` | `sudo pacman -S chromaprint` |
| openSUSE | `sudo zypper install ffmpeg` | `sudo zypper install chromaprint-fpcalc` |
| macOS | `brew install ffmpeg` | `brew install chromaprint` |
| Windows | `winget install Gyan.FFmpeg` | [download fpcalc](https://acoustid.org/chromaprint) and put it on `PATH` |

`make deps` runs the right line for you on Linux and macOS; on Windows install
the two by hand. Chromaprint publishes no Windows package manager entry, so
`fpcalc.exe` comes from the zip on the AcoustID download page.

## Use

Put one album per subfolder in `input/`, then:

```bash
m3talist scan                  # read tags into the catalog and assign the order
m3talist build                 # write output/ in play order
m3talist copy /run/media/you/PLAYER   # sequential copy, one file at a time
```

Or drive it from the terminal UI:

```bash
m3talist serve                 # http://127.0.0.1:8420
```

### Other commands

```bash
m3talist list                  # catalogued releases
m3talist groups --by genre     # counts by genre, year or artist
m3talist dupes                 # duplicate recordings (needs fpcalc)
m3talist calibrate             # cover-art test ladder for your device
m3talist config --cover-max-px 300
```

## When input/ changes

The catalog is a snapshot, so editing a file does not update it on its own. Every
page compares a cheap signature of `input/` — path, size and mtime of each audio
file — against the one recorded at the last scan, and shows a **RELOAD** banner
when they differ. No watcher process, and it still notices edits made while
m3talist was not running.

```bash
m3talist scan            # reload: additive, keeps manual track orders
m3talist scan --fresh    # reset: discard the catalog and read input/ from scratch
```

A reload refreshes everything the file owns — tags, codec, bitrate, sample rate,
duration — and drops the stored fingerprint when the bytes changed. Use `--fresh`
(or the amber RESET button) only when you want the manual orders gone too.

## Albums with no track numbers

If a release has neither `TRCK` nor numbered filenames, its order cannot be
guessed safely, so it is flagged and left out of the build — the rest of the
library still builds. Open it in the web UI, drag the tracks into place, save. The
order is stored and never asked again.

## Cover art

Off by default. Nobody has published what artwork the SL6801 tolerates, so
`m3talist calibrate` writes a ladder of identical files with escalating cover
sizes. Play them on the device, find the last one that works, and record it with
`m3talist config --cover-max-px <size>`.

## Docs

- [Spec](docs/m3talist-v2.md) — problem, solution, data model, flows
- [Device dossier](docs/device-sl680x.md) — chip identification, what was settled and why
- [Implementation plan](docs/implementation-plan-v2.md)
