import asyncio
import json
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from m3talist import catalog, fingerprint, ordering, pipeline, profile, tags
from m3talist.config import CALIBRATE_DIR, OUTPUT_DIR, prepare_paths
from m3talist.web.jobs import JOB

HERE = Path(__file__).parent

app = FastAPI(title="m3talist")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


def get_conn():
    prepare_paths()
    conn = catalog.connect()
    try:
        yield conn
    finally:
        conn.close()


def render(request: Request, template: str, conn, screen: str, **extra):
    track_total, review_total = catalog.counts(conn)
    base = {
        "screen": screen,
        "frames": tags.FRAMES,
        "settings": profile.load(),
        "track_total": track_total,
        "review_total": review_total,
        "input_stale": pipeline.input_changed(conn),
    }
    base.update(extra)
    return templates.TemplateResponse(request, template, base)


def background(name: str, work) -> None:
    """One job at a time; a second request while running is ignored.

    Wrapping `work` here — rather than in every route — guarantees JOB.running
    is always cleared, even if `work` raises. No job body has to remember to
    catch its own exceptions to keep the job system alive.
    """
    if not JOB.start(name):
        return

    def guarded():
        try:
            work()
        except Exception as exc:
            JOB.emit(f"error {exc}")
        finally:
            if JOB.running:
                JOB.finish(f"{name.lower()} failed")

    threading.Thread(target=guarded, daemon=True).start()


@app.get("/", response_class=HTMLResponse)
def library(request: Request, conn=Depends(get_conn)):
    track_counts = catalog.track_counts(conn)
    rows = [
        (release, range(track_counts.get(release.id, 0)))
        for release in catalog.releases(conn)
    ]
    return render(request, "library.html", conn, "LIBRARY", rows=rows)


@app.get("/release/{release_id}", response_class=HTMLResponse)
def release_detail(request: Request, release_id: int, conn=Depends(get_conn)):
    return render(request, "release.html", conn, "RELEASE",
                  release=catalog.release(conn, release_id),
                  tracks=catalog.tracks_of(conn, release_id))


@app.post("/release/{release_id}/order")
def save_order(release_id: int, track_ids: str = Form(...), conn=Depends(get_conn)):
    ids = [int(i) for i in track_ids.split(",") if i]
    known_ids = {track.id for track in catalog.tracks_of(conn, release_id)}
    if not ids or any(track_id not in known_ids for track_id in ids):
        raise HTTPException(400, "track ids do not belong to this release")
    ordering.reorder(conn, release_id, ids)
    ordering.assign(conn)
    return RedirectResponse(f"/release/{release_id}", status_code=303)


@app.get("/build", response_class=HTMLResponse)
def build_screen(request: Request, conn=Depends(get_conn)):
    output_count = len(list(OUTPUT_DIR.glob("*.mp3"))) if OUTPUT_DIR.exists() else 0
    return render(request, "build.html", conn, "BUILD", output_count=output_count)


@app.post("/scan")
def start_scan(fresh: str = Form("")):
    """Reload input/ into the catalog. fresh=on discards it first."""
    wipe = fresh == "on"

    def work():
        conn = catalog.connect()
        try:
            if wipe:
                JOB.emit("resetting catalog")
            result = pipeline.scan(
                conn,
                fresh=wipe,
                on_progress=lambda done, total, name: (
                    JOB.progress(done, total), JOB.emit(f"reading {name}")
                ),
            )
            for note in result.skipped:
                JOB.emit(f"skipped {note}")
            for name in result.needs_review:
                JOB.emit(f"needs review {name}")
            JOB.finish(f"{result.releases} releases · {result.tracks} tracks")
        finally:
            conn.close()

    background("SCAN", work)
    return RedirectResponse("/build", status_code=303)


@app.post("/build")
def start_build():
    def work():
        conn = catalog.connect()
        try:
            result = pipeline.build(
                conn,
                on_progress=JOB.progress,
                on_log=lambda name: JOB.emit(f"wrote {name}"),
            )
            JOB.set_failed(result.failed)
            for error in result.errors[:20]:
                JOB.emit(f"error {error}")
            JOB.finish(f"{result.written} written · {result.failed} failed")
        finally:
            conn.close()

    background("BUILD", work)
    return RedirectResponse("/build", status_code=303)


@app.post("/enrich")
def start_enrich():
    def work():
        conn = catalog.connect()
        try:
            covers = pipeline.enrich(
                conn,
                on_progress=lambda done, total, name: (
                    JOB.progress(done, total), JOB.emit(f"lookup {name}")
                ),
            )
            JOB.finish(f"{len(covers)} covers cached")
        finally:
            conn.close()

    background("ENRICH", work)
    return RedirectResponse("/build", status_code=303)


@app.post("/dupes")
def start_dupes():
    def work():
        conn = catalog.connect()
        try:
            report = fingerprint.scan(
                conn, catalog.all_tracks(conn), on_progress=JOB.progress
            )
            if report.too_short:
                JOB.emit(f"{report.too_short} too short to fingerprint")
            if report.fingerprint_failed:
                JOB.emit(f"{report.fingerprint_failed} unreadable by fpcalc")
            if not report.fpcalc_available:
                JOB.emit("fpcalc absent — matching byte-identical audio only")
            JOB.finish(
                f"{report.hashed} hashed · {report.fingerprinted} fingerprinted"
            )
        finally:
            conn.close()

    background("FINGERPRINT", work)
    return RedirectResponse("/build", status_code=303)


@app.get("/stream")
async def stream():
    async def events():
        sent = 0
        while True:
            snapshot = JOB.snapshot()
            # `log` is a bounded deque: once it saturates, its length stops
            # tracking how many lines were ever emitted. `seq` is monotonic
            # and never resets except on a new job, so slice by it instead.
            # If more lines were dropped than the deque still holds, this
            # just sends everything left rather than freezing.
            new = snapshot["seq"] - sent
            delta = snapshot["log"][-new:] if new > 0 else []
            sent = snapshot["seq"]
            payload = {**snapshot, "log": delta}
            yield f"data: {json.dumps(payload)}\n\n"
            if not snapshot["running"]:
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(0.2)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/dupes", response_class=HTMLResponse)
def dupes(request: Request, conn=Depends(get_conn)):
    return render(request, "dupes.html", conn, "DUPES",
                  groups=fingerprint.duplicates(conn),
                  fpcalc=fingerprint.available())


@app.get("/calibrate", response_class=HTMLResponse)
def calibrate_screen(request: Request, conn=Depends(get_conn)):
    written = sorted(CALIBRATE_DIR.glob("*.mp3")) if CALIBRATE_DIR.exists() else []
    return render(request, "calibrate.html", conn, "CALIBRATE", written=written)


@app.post("/calibrate")
def run_calibrate():
    def work():
        written = pipeline.calibrate()
        JOB.finish(f"{len(written)} calibration files written")

    background("CALIBRATE", work)
    return RedirectResponse("/calibrate", status_code=303)


@app.get("/config", response_class=HTMLResponse)
def config_screen(request: Request, conn=Depends(get_conn)):
    return render(request, "config.html", conn, "CONFIG",
                  genres=catalog.group_by(conn, "genre"),
                  years=catalog.group_by(conn, "year"))


@app.post("/config")
def save_config(cover_max_px: str = Form(""), offline: str = Form("")):
    current = profile.load()
    px = int(cover_max_px) if cover_max_px.strip().isdigit() else 0
    profile.save(
        profile.Settings(
            cover_max_px=px or None,
            offline=offline == "on",
            user_agent=current.user_agent,
        )
    )
    return RedirectResponse("/config", status_code=303)
