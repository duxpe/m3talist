from m3talist import catalog, pipeline


EXPECTED_ORDER = [
    "0001-autobahn.mp3",
    "0002-kometenmelodie.mp3",
    "0003-mitternacht.mp3",
    "0004-speak-to-me.mp3",
    "0005-breathe.mp3",
    "0006-time.mp3",
    "0007-eclipse.mp3",
]


def test_build_writes_albums_in_play_order(conn, library, tmp_path):
    """Happy path: shuffled filenames, intact TRCK, correct order on disk.

    written is asserted unsorted against EXPECTED_ORDER on purpose: a build that
    writes everything backwards still produces the same *sorted* set of names, so
    `sorted(written) == sorted(EXPECTED_ORDER)` would pass either way. That exact
    assertion shipped once and hid a real reversed-order bug. on_log fires inside
    the sequential move loop, so `written` IS the order files were created in —
    the guarantee the device depends on — and only an unsorted comparison catches
    a regression here.
    """
    output = tmp_path / "output"
    output.mkdir()

    scan_result = pipeline.scan(conn, input_dir=library)
    assert scan_result.releases == 3
    assert scan_result.tracks == 10
    assert scan_result.needs_review == ["Various - Mixtape"]

    written = []
    build = pipeline.build(conn, output_dir=output, workers=2, on_log=written.append)
    assert build.failed == 0
    assert build.written == 7

    assert written == EXPECTED_ORDER
    assert sorted(p.name for p in output.glob("*.mp3")) == EXPECTED_ORDER


def test_unorderable_release_is_isolated_not_fatal(conn, library, tmp_path):
    """Edge case: one bad album must not cost the other nine tracks."""
    output = tmp_path / "output"
    output.mkdir()
    pipeline.scan(conn, input_dir=library)

    mixtape = next(r for r in catalog.releases(conn) if r.title == "Mixtape")
    assert mixtape.needs_review
    assert all(t.sort_index is None for t in catalog.tracks_of(conn, mixtape.id))

    build = pipeline.build(conn, output_dir=output, workers=2)
    assert "Various - Mixtape" in build.skipped_releases
    assert build.written == 7
    assert not list(output.glob("*alpha*"))


def test_manual_review_puts_the_album_back_in_the_build(conn, library, tmp_path):
    from m3talist import ordering

    output = tmp_path / "output"
    output.mkdir()
    pipeline.scan(conn, input_dir=library)

    mixtape = next(r for r in catalog.releases(conn) if r.title == "Mixtape")
    tracks = catalog.tracks_of(conn, mixtape.id)
    ordering.reorder(conn, mixtape.id, [t.id for t in reversed(tracks)])
    ordering.assign(conn)

    assert not catalog.release(conn, mixtape.id).needs_review
    build = pipeline.build(conn, output_dir=output, workers=2)
    assert build.written == 10
    assert (output / "0008-charlie.mp3").exists()


def test_rescan_refreshes_data_derived_from_the_file(conn, library):
    """A re-encoded source must update the cached stream info.

    build() decides copy-vs-transcode from these columns, so a stale row would
    pass a 320k/48k/mono file straight through to a device that needs CBR
    128k/44.1k/stereo.
    """
    import subprocess

    from m3talist import catalog

    source = library / "Pink Floyd - The Dark Side of the Moon" / "time.mp3"
    original = source.read_bytes()
    try:
        pipeline.scan(conn, input_dir=library)
        track = next(t for t in catalog.all_tracks(conn) if t.source_path == source)
        catalog.set_fingerprint(conn, track.id, "stale-fingerprint")
        conn.commit()
        assert track.audio.sample_rate == 44100

        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", "sine=frequency=500:duration=2", "-c:a", "libmp3lame",
             "-b:a", "320k", "-ar", "48000", "-ac", "1", str(source)],
            check=True,
        )
        pipeline.scan(conn, input_dir=library)

        refreshed = next(t for t in catalog.all_tracks(conn) if t.source_path == source)
        assert refreshed.audio.bitrate == 320000
        assert refreshed.audio.sample_rate == 48000
        assert refreshed.audio.channels == 1
        assert refreshed.fingerprint is None, "rewritten bytes invalidate the fingerprint"
    finally:
        source.write_bytes(original)


def test_input_changed_notices_an_edit_without_a_watcher(conn, library):
    from m3talist import catalog

    source = library / "Kraftwerk - Autobahn" / "01 - Autobahn.mp3"
    original = source.read_bytes()
    try:
        pipeline.scan(conn, input_dir=library)
        assert not pipeline.input_changed(conn, library)

        source.write_bytes(original + b"\x00")
        assert pipeline.input_changed(conn, library)

        pipeline.scan(conn, input_dir=library)
        assert not pipeline.input_changed(conn, library)
    finally:
        source.write_bytes(original)
        catalog.set_meta(conn, pipeline.SIGNATURE_KEY, pipeline.input_signature(library))


def test_dedupe_catches_a_retagged_copy_in_another_album(conn, library):
    """The common case: one track copied into a second album and retagged.

    Hashing the decoded stream ignores tags, so this matches without fpcalc and
    regardless of how short the audio is.
    """
    from mutagen.id3 import ID3, TIT2

    from m3talist import catalog, fingerprint

    source = library / "Pink Floyd - The Dark Side of the Moon" / "breathe.mp3"
    copy = library / "Kraftwerk - Autobahn" / "atmen.mp3"
    copy.write_bytes(source.read_bytes())
    tags = ID3(copy, v2_version=3)
    tags.setall("TIT2", [TIT2(encoding=1, text=["Atmen"])])
    tags.save(copy, v2_version=3)

    try:
        pipeline.scan(conn, input_dir=library)
        report = fingerprint.scan(conn, catalog.all_tracks(conn))
        assert report.hashed > 0

        identical = [g for kind, g in fingerprint.duplicates(conn) if kind == "identical audio"]
        paths = [{t.source_path for t in group} for group in identical]
        assert {source, copy} in paths
    finally:
        copy.unlink()


def test_copy_to_preserves_creation_order(conn, library, tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    device = tmp_path / "device"
    pipeline.scan(conn, input_dir=library)
    pipeline.build(conn, output_dir=output, workers=2)

    order = []
    copied = pipeline.copy_to(device, output_dir=output, on_log=order.append)
    assert copied == 7
    assert order == EXPECTED_ORDER
