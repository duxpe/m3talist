import argparse
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from m3talist import catalog, fingerprint, ordering, pipeline, profile
from m3talist.audio import ToolMissing
from m3talist.config import INPUT_DIR, OUTPUT_DIR, prepare_paths

LOGO = """[bright_green]▖  ▖▄▖▄▖▄▖▖ ▄▖▄▖▄▖
▛▖▞▌▄▌▐ ▌▌▌ ▐ ▚ ▐
▌▝ ▌▄▌▐ ▛▌▙▖▟▖▄▌▐[/bright_green]  [dim]v2[/dim]"""

console = Console()


def _progress() -> Progress:
    return Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(complete_style="bright_green", finished_style="bright_green"),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
    )


def _open() -> sqlite3.Connection:
    prepare_paths()
    return catalog.connect()


def cmd_scan(args) -> int:
    conn = _open()
    with _progress() as bar:
        task = bar.add_task("READING", total=None)
        result = pipeline.scan(
            conn,
            fresh=args.fresh,
            force_alpha=args.force_alpha,
            on_progress=lambda done, total, name: bar.update(
                task, completed=done, total=total, description=f"READING {name[:28]}"
            ),
        )
    console.print(f"[bright_green]{result.releases}[/bright_green] releases, "
                  f"[bright_green]{result.tracks}[/bright_green] tracks")
    for note in result.skipped:
        console.print(f"[yellow]skipped[/yellow] {note}")
    for name in result.needs_review:
        console.print(f"[yellow]⚠ ORDER[/yellow] {name} — no track numbers, excluded from build")
    return 0


def cmd_build(args) -> int:
    conn = _open()
    try:
        with _progress() as bar:
            task = bar.add_task("ENCODING", total=1)
            result = pipeline.build(
                conn,
                workers=args.workers,
                on_progress=lambda done, total: bar.update(task, completed=done, total=total),
            )
    except ToolMissing as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    console.print(f"[bright_green]{result.written}[/bright_green] written to {OUTPUT_DIR}")
    if result.failed:
        console.print(f"[red]{result.failed} failed[/red]")
        for error in result.errors[:10]:
            console.print(f"  [red]{error}[/red]")
    for name in result.skipped_releases:
        console.print(f"[yellow]⚠ ORDER[/yellow] {name} — skipped, needs review")
    return 1 if result.failed else 0


def cmd_enrich(args) -> int:
    conn = _open()
    with _progress() as bar:
        task = bar.add_task("MUSICBRAINZ", total=None)
        covers = pipeline.enrich(
            conn,
            on_progress=lambda done, total, name: bar.update(
                task, completed=done, total=total, description=f"LOOKUP {name[:26]}"
            ),
        )
    settings = profile.load()
    console.print(f"[bright_green]{len(covers)}[/bright_green] covers cached")
    if not settings.cover_enabled:
        console.print("[dim]covers disabled — run calibrate, then config --cover-max-px[/dim]")
    return 0


def cmd_copy(args) -> int:
    total = pipeline.copy_to(Path(args.dest))
    console.print(f"[bright_green]{total}[/bright_green] files copied in order to {args.dest}")
    return 0


def cmd_calibrate(args) -> int:
    try:
        written = pipeline.calibrate()
    except ToolMissing as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    console.print(LOGO)
    console.print("\n[bright_green]COVER CALIBRATION[/bright_green]\n")
    for path in written:
        console.print(f"  {path.name}")
    console.print(
        "\nCopy these to the device and play each one.\n"
        "Note the last file that plays cleanly, then record it:\n"
        "  [bright_green]m3talist config --cover-max-px <size>[/bright_green]\n"
        "If even 100px misbehaves, leave covers off."
    )
    return 0


def cmd_list(args) -> int:
    conn = _open()
    table = Table(box=None, header_style="bright_green")
    table.add_column("ARTIST · TPE2")
    table.add_column("ALBUM · TALB")
    table.add_column("YEAR", justify="right")
    table.add_column("TRACKS", justify="right")
    table.add_column("STATE")
    for release in catalog.releases(conn):
        tracks = catalog.tracks_of(conn, release.id)
        state = "[yellow]⚠ ORDER[/yellow]" if release.needs_review else "[dim]ready[/dim]"
        table.add_row(release.artist, release.title, str(release.year or "—"),
                      str(len(tracks)), state)
    console.print(table)
    return 0


def cmd_dupes(args) -> int:
    conn = _open()
    tracks = catalog.all_tracks(conn)
    with _progress() as bar:
        task = bar.add_task("HASHING", total=len(tracks))
        report = fingerprint.scan(
            conn, tracks, on_progress=lambda done, total: bar.update(task, completed=done)
        )

    covered = catalog.all_tracks(conn)
    with_hash = sum(1 for t in covered if t.content_hash)
    with_print = sum(1 for t in covered if t.fingerprint)
    console.print(f"[bright_green]{with_hash}/{len(covered)}[/bright_green] hashed "
                  f"[dim](+{report.hashed} this run)[/dim], "
                  f"[bright_green]{with_print}/{len(covered)}[/bright_green] fingerprinted "
                  f"[dim](+{report.fingerprinted})[/dim]")
    if not report.fpcalc_available:
        console.print("[dim]fpcalc absent — only byte-identical audio is matched. "
                      "`make deps` enables cross-encoding matching.[/dim]")
    if report.too_short:
        console.print(f"[yellow]{report.too_short} file(s) too short to fingerprint[/yellow] "
                      f"[dim](chromaprint needs ~{fingerprint.MIN_FINGERPRINT_SECONDS}s)[/dim]")
    if report.fingerprint_failed:
        console.print(f"[yellow]{report.fingerprint_failed} file(s) fpcalc could not "
                      f"read[/yellow]")
    for name in report.unreadable[:5]:
        console.print(f"[red]could not hash {name}[/red]")

    groups = fingerprint.duplicates(conn)
    if not groups:
        console.print("[bright_green]no duplicates[/bright_green]")
        return 0
    for kind, group in groups:
        console.print(f"\n[yellow]{len(group)} copies[/yellow] [dim]({kind})[/dim]")
        for track in group:
            console.print(f"  {track.source_path}")
    return 0


def cmd_groups(args) -> int:
    conn = _open()
    table = Table(box=None, header_style="bright_green")
    table.add_column(args.by.upper())
    table.add_column("TRACKS", justify="right")
    for label, total in catalog.group_by(conn, args.by):
        table.add_row(str(label), str(total))
    console.print(table)
    return 0


def cmd_config(args) -> int:
    settings = profile.load()
    changes = {}
    if args.cover_max_px is not None:
        changes["cover_max_px"] = None if args.cover_max_px == 0 else args.cover_max_px
    if args.offline is not None:
        changes["offline"] = args.offline
    if changes:
        settings = replace(settings, **changes)
        profile.save(settings)
    console.print(f"cover_max_px = {settings.cover_max_px or 'off'}")
    console.print(f"offline      = {settings.offline}")
    return 0


def cmd_review(args) -> int:
    conn = _open()
    ordering.reorder(conn, args.release, [int(i) for i in args.tracks])
    ordering.assign(conn)
    console.print("[bright_green]order recorded[/bright_green]")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    console.print(LOGO)
    console.print(f"\n[bright_green]TERMINAL ONLINE[/bright_green] http://{args.host}:{args.port}\n")
    uvicorn.run("m3talist.web.app:app", host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="m3talist", description="Device-safe music library builder")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help=f"read {INPUT_DIR} into the catalog")
    scan.add_argument("--fresh", action="store_true",
                      help="discard the catalog first, losing any manual track order")
    scan.add_argument("--force-alpha", action="store_true",
                      help="order releases missing track numbers by file path instead of "
                           "flagging them for review")
    scan.set_defaults(run=cmd_scan)

    build = sub.add_parser("build", help="write the flat collection in play order")
    build.add_argument("--workers", type=int, default=None)
    build.set_defaults(run=cmd_build)

    sub.add_parser("enrich", help="fill gaps from MusicBrainz and cache covers").set_defaults(
        run=cmd_enrich
    )

    copy = sub.add_parser("copy", help="copy output to the device, one file at a time")
    copy.add_argument("dest")
    copy.set_defaults(run=cmd_copy)

    sub.add_parser("calibrate", help="generate the cover-art ladder").set_defaults(run=cmd_calibrate)
    sub.add_parser("list", help="show catalogued releases").set_defaults(run=cmd_list)
    sub.add_parser("dupes", help="find duplicate recordings").set_defaults(run=cmd_dupes)

    groups = sub.add_parser("groups", help="count tracks by a field")
    groups.add_argument("--by", default="genre", choices=["genre", "year", "artist", "album_artist"])
    groups.set_defaults(run=cmd_groups)

    config = sub.add_parser("config", help="read or change settings")
    config.add_argument("--cover-max-px", type=int, default=None,
                        help="last cover size the device handled; 0 disables covers")
    config.add_argument("--offline", type=lambda v: v.lower() == "true", default=None)
    config.set_defaults(run=cmd_config)

    review = sub.add_parser("review", help="record a manual track order")
    review.add_argument("release", type=int)
    review.add_argument("tracks", nargs="+")
    review.set_defaults(run=cmd_review)

    serve = sub.add_parser("serve", help="start the web terminal")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8420)
    serve.set_defaults(run=cmd_serve)

    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
