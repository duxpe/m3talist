from pathlib import Path

from mutagen.id3 import ID3, TSSE

from m3talist import tags
from m3talist.models import Release, Track


def _pair(path: Path, **track_kwargs):
    track = Track(source_path=path, title="Time", artist="Pink Floyd", genre="Rock",
                  track_no=4, **track_kwargs)
    release = Release(artist="Pink Floyd", title="The Dark Side of the Moon",
                      source_dir=path.parent, year=1973)
    return track, release


def test_round_trip_writes_a_v23_tag_with_a_v1_tail(make_mp3):
    path = make_mp3("t.mp3")
    track, release = _pair(path)

    tags.write(path, track, release, total_tracks=10)

    stored = ID3(path, v2_version=3)
    assert stored.version[:2] == (2, 3)
    assert str(stored["TIT2"]) == "Time"
    assert str(stored["TRCK"]) == "4/10"
    # Album-wide frames come off the release, not the track.
    assert str(stored["TALB"]) == "The Dark Side of the Moon"
    assert str(stored["TPE2"]) == "Pink Floyd"
    assert path.read_bytes()[-128:][:3] == b"TAG"

    read_back = tags.read(path)
    assert read_back["title"] == "Time"
    assert read_back["track_no"] == 4
    assert read_back["year"] == 1973


def test_year_uses_tyer_never_tdrc(make_mp3):
    """TDRC is ID3v2.4. Old firmware does not know it, so it must never appear."""
    path = make_mp3("y.mp3")
    track, release = _pair(path)

    tags.write(path, track, release)

    stored = ID3(path, v2_version=3)
    assert "TYER" in stored
    assert "TDRC" not in stored


def test_unmanaged_frames_survive_a_rewrite(make_mp3):
    """The old code called delete(), which wiped TRCK and broke album order.
    Only the frames m3talist manages may be touched."""
    path = make_mp3("k.mp3")
    existing = ID3(path, v2_version=3)
    existing.add(TSSE(encoding=1, text=["handmade"]))
    existing.save(path, v2_version=3)

    track, release = _pair(path)
    tags.write(path, track, release, total_tracks=10)
    tags.write(path, track, release, total_tracks=10)

    stored = ID3(path, v2_version=3)
    assert str(stored["TSSE"]) == "handmade"
    assert str(stored["TRCK"]) == "4/10"


def test_disc_number_only_appears_on_multi_disc_sets(make_mp3):
    single = make_mp3("s.mp3")
    track, release = _pair(single, disc_no=1)
    tags.write(single, track, release, total_tracks=10, total_discs=1)
    assert "TPOS" not in ID3(single, v2_version=3)

    double = make_mp3("d.mp3")
    track, release = _pair(double, disc_no=2)
    tags.write(double, track, release, total_tracks=10, total_discs=2)
    assert str(ID3(double, v2_version=3)["TPOS"]) == "2"


def test_read_never_raises_on_a_broken_file(tmp_path):
    junk = tmp_path / "broken.mp3"
    junk.write_bytes(b"not audio at all")
    assert tags.read(junk)["title"] is None


def test_cover_is_embedded_only_when_supplied(make_mp3):
    path = make_mp3("c.mp3")
    track, release = _pair(path)

    tags.write(path, track, release, cover=None)
    assert not ID3(path, v2_version=3).getall("APIC")

    tags.write(path, track, release, cover=b"\xff\xd8\xff\xe0stub")
    assert len(ID3(path, v2_version=3).getall("APIC")) == 1

    tags.write(path, track, release, cover=None)
    assert not ID3(path, v2_version=3).getall("APIC")
