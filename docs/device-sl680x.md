# Device dossier: Smartlink SL680x

Reference hardware for [m3talist-v2](./m3talist-v2.md). Sold as GENAI — a Brazilian
reseller brand, not a manufacturer — reporting firmware `yp3_2.0.43`. Library in
use: ~523 tracks, flat, working.

## Identification

The `yp3_` firmware prefix identifies the chip family: Smartlink **SL6801 /
SL6806**, labelled "Jointbees MP3", per
[smartlink_flash](https://github.com/ilyakurdyukov/smartlink_flash). `YP3` is 云P3
(*yún P3*) — unrelated to Samsung's `YP-` line. Not Actions, JieLi, Anyka or
Rockchip, which is where most community knowledge about cheap players lives.

VID `301a` is absent from the official `usb.ids`, so `lsusb` prints the raw ID with
no vendor name.

| | SL6801 | SL6806 |
|---|---|---|
| Card reader | `301a:2801` | `301a:2800` |
| Bootloader | `301a:2800` | `301a:2800` |
| `iSerial` | `20201111000001` | `20220320000001` |

`iSerial` is the reliable discriminator — `smtlink_dump.c` compares those exact
strings to pick the chip. `iProduct` reads `SMTLINK CARDREADER 1.00`,
`SMTLINK DEVICE 2.00` or `SSTLINK DDVICE 2.02` (the typos are in the firmware).

```bash
lsusb                          # find the VID:PID
lsusb -v -d 301a:2800          # iSerial, iProduct, bcdDevice
blkid /dev/sdX1                # FAT label and volume serial
```

## What is not knowable from documentation

Smartlink publishes no SDK. The nearest reference, JieLi's `music_id3.h`, exposes
only `id3_v1_obj_get` / `id3_v2_obj_get` over a precompiled `.a` — signatures, no
implementation.

So there is **no source of truth** for how this chip handles ID3 version, text
encoding, or embedded cover art. Any such claim about these players is reverse
engineering of a binary, not spec.

## Settled without testing

Untested does not mean unknown-what-to-do. Where the safe option costs nothing,
the safe option wins and no experiment is warranted:

| Dimension | Choice | Why no test |
|---|---|---|
| Tag version | ID3v2.3 + ID3v1 tail | v2.4 working would not change the choice |
| Text encoding | UTF-16 with BOM | worst-case-safe; ASCII filenames regardless |
| Year frame | `TYER` | v2.4's `TDRC` is unknown to old parsers |
| Bitrate | CBR 128 kbps / 44.1 kHz / stereo | already a fixed project target |
| Track order | all four layers always | ordering is deliberately redundant, so which channel the firmware honours does not change the build |
| Files per folder | no limit enforced | 523 flat already works on this unit |

## The one open question: cover art

Cover art is the only dimension where the answer is unknown, the safe default
(none) is a loss rather than a cost, and the result changes what the tool writes.

`calibrate` writes a ladder of otherwise identical MP3s: no cover, then 100×100,
200×200, 300×300, 500×500 as baseline JPEG, plus one progressive JPEG at the
largest size that still worked. The user plays them and notes where the device
stalls, garbles or reboots. The last good rung becomes `cover_max_px` in config;
if even 100×100 fails, covers stay off for good.

One run, one line of config, permanent.

## Firmware tooling

Not needed for m3talist, recorded for completeness.
[smartlink_flash](https://github.com/ilyakurdyukov/smartlink_flash) can dump and
write flash on these chips (`read_flash`, `write_flash`, `erase_flash`). Its
sibling `actions_flash` is self-described as unfinished with a risk of bricking;
assume the same here. Reading a dump and running `strings -n 6` on it would reveal
the SDK banner and could settle the ID3 questions above — a curiosity, not a
dependency.
