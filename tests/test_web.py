import json
import time

import pytest
from fastapi.testclient import TestClient

from m3talist.web import app as web
from m3talist.web.jobs import JOB


@pytest.fixture
def client():
    JOB.finish("")
    JOB.running = False
    return TestClient(web.app)


def _stream_lines(client) -> list[str]:
    lines = []
    with client.stream("GET", "/stream") as response:
        for chunk in response.iter_lines():
            if not chunk.startswith("data: "):
                continue
            payload = json.loads(chunk[6:])
            lines.extend(payload["log"])
            if not payload["running"]:
                break
    return lines


def test_stream_survives_more_lines_than_the_log_buffer_holds(client):
    """The log is a bounded deque. Slicing the delta by list length freezes
    forever once it saturates; slicing by sequence keeps delivering.

    The stream must be consumed while the job is still producing — reading it
    after the job ends hides the bug, because a single final poll returns the
    whole surviving tail either way.
    """
    total = JOB.log.maxlen + 120

    def work():
        for index in range(total):
            JOB.emit(f"line-{index}")
            time.sleep(0.002)
        JOB.finish("done")

    web.background("TEST", work)
    delivered = _stream_lines(client)

    assert delivered[-1] == f"line-{total - 1}"
    assert len(delivered) == total, "lines were dropped once the deque saturated"


def test_a_crashing_job_never_wedges_the_runner(client):
    """One unhandled exception used to leave running=True forever, silently
    rejecting every later job."""

    def explode():
        raise RuntimeError("boom")

    web.background("EXPLODE", explode)
    while JOB.snapshot()["running"]:
        time.sleep(0.02)

    assert JOB.snapshot()["running"] is False

    finished = []
    web.background("AFTER", lambda: finished.append(True))
    while JOB.snapshot()["running"]:
        time.sleep(0.02)
    assert finished == [True]


def test_save_order_rejects_tracks_from_another_release(client, library, tmp_path):
    from m3talist import catalog, pipeline

    conn = catalog.connect(tmp_path / "web.db")
    pipeline.scan(conn, input_dir=library)
    releases = catalog.releases(conn)
    target = releases[0]
    stranger = catalog.tracks_of(conn, releases[1].id)[0]
    conn.close()

    def use_test_db():
        connection = catalog.connect(tmp_path / "web.db")
        try:
            yield connection
        finally:
            connection.close()

    web.app.dependency_overrides[web.get_conn] = use_test_db
    try:
        response = client.post(
            f"/release/{target.id}/order",
            data={"track_ids": str(stranger.id)},
            follow_redirects=False,
        )
        assert response.status_code == 400
    finally:
        web.app.dependency_overrides.clear()
