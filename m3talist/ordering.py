from m3talist import catalog, naming


def assign(conn, force_alpha: bool = False) -> list[str]:
    orderable = []
    tracks_by_release = {}
    skipped = []

    for release in catalog.releases(conn):
        tracks = catalog.tracks_of(conn, release.id)
        missing_order = any(track.track_no is None for track in tracks)
        if missing_order and not force_alpha:
            catalog.set_review(conn, release.id, True)
            skipped.append(f"{release.artist} - {release.title}")
            continue
        catalog.set_review(conn, release.id, False)
        if missing_order:
            tracks_by_release[release.id] = sorted(tracks, key=lambda track: str(track.source_path))
        else:
            tracks_by_release[release.id] = sorted(
                tracks, key=lambda track: (track.disc_no or 1, track.track_no)
            )
        orderable.append(release)

    orderable.sort(
        key=lambda release: (release.artist.casefold(), release.year or 9999, release.title.casefold())
    )

    total = sum(len(tracks_by_release[release.id]) for release in orderable)
    width = max(4, len(str(total)))

    sort_index = 1
    for release in orderable:
        for track in tracks_by_release[release.id]:
            name = naming.output_name(sort_index, track, width)
            catalog.set_order(conn, track.id, sort_index, name)
            sort_index += 1

    conn.commit()
    return skipped


def reorder(conn, release_id: int, track_ids: list[int]) -> None:
    for position, track_id in enumerate(track_ids):
        catalog.set_track_no(conn, track_id, position + 1)
    catalog.set_review(conn, release_id, False)
    conn.commit()
