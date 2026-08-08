from pathlib import Path

from m3talist import catalog, ordering
from m3talist.models import Release, Track


def _seed(conn, artist: str, title: str, track_numbers, year=None, discs=None):
    release = Release(artist=artist, title=title, source_dir=Path(f"/tmp/{artist}-{title}"),
                      year=year)
    release_id = catalog.add_release(conn, release)
    for position, track_no in enumerate(track_numbers):
        catalog.add_track(
            conn,
            Track(
                source_path=Path(f"/tmp/{artist}-{title}/{position}.mp3"),
                title=f"{title} {position}",
                track_no=track_no,
                disc_no=discs[position] if discs else None,
            ),
            release_id,
        )
    conn.commit()
    return release_id


def test_global_index_runs_across_releases_in_artist_order(conn):
    _seed(conn, "Zeta", "Late", [1, 2], year=1990)
    _seed(conn, "Alpha", "Early", [1, 2, 3], year=1980)

    assert ordering.assign(conn) == []

    names = [track.output_name for track in catalog.buildable_tracks(conn)]
    assert names == [
        "0001-early-0.mp3",
        "0002-early-1.mp3",
        "0003-early-2.mp3",
        "0004-late-0.mp3",
        "0005-late-1.mp3",
    ]


def test_one_missing_track_number_flags_the_whole_release(conn):
    good = _seed(conn, "Alpha", "Complete", [1, 2])
    bad = _seed(conn, "Beta", "Partial", [1, None, 3])

    skipped = ordering.assign(conn)

    assert skipped == ["Beta - Partial"]
    assert catalog.release(conn, bad).needs_review
    assert all(t.sort_index is None for t in catalog.tracks_of(conn, bad))
    # The healthy release keeps its order regardless.
    assert not catalog.release(conn, good).needs_review
    assert [t.sort_index for t in catalog.tracks_of(conn, good)] == [1, 2]


def test_discs_order_before_track_numbers(conn):
    release_id = _seed(conn, "Alpha", "Double", [1, 2, 1, 2], discs=[2, 2, 1, 1])
    ordering.assign(conn)

    ordered = sorted(catalog.tracks_of(conn, release_id), key=lambda t: t.sort_index)
    assert [(t.disc_no, t.track_no) for t in ordered] == [(1, 1), (1, 2), (2, 1), (2, 2)]


def test_reorder_records_the_choice_and_clears_review(conn):
    release_id = _seed(conn, "Beta", "Partial", [None, None, None])
    ordering.assign(conn)
    assert catalog.release(conn, release_id).needs_review

    tracks = catalog.tracks_of(conn, release_id)
    ordering.reorder(conn, release_id, [tracks[2].id, tracks[0].id, tracks[1].id])

    assert not catalog.release(conn, release_id).needs_review
    ordering.assign(conn)
    ordered = sorted(catalog.buildable_tracks(conn), key=lambda t: t.sort_index)
    assert [t.id for t in ordered] == [tracks[2].id, tracks[0].id, tracks[1].id]


def test_force_alpha_orders_by_path_instead_of_skipping(conn):
    release_id = _seed(conn, "Beta", "Partial", [None, None])

    assert ordering.assign(conn, force_alpha=True) == []
    assert not catalog.release(conn, release_id).needs_review
    assert len(catalog.buildable_tracks(conn)) == 2
