"""Tests for resources/lib/playlist.py (FR-006, FR-010, D-009, SC-004/SC-005)."""

import os
import pathlib
from typing import Any, List

import pytest
import xbmc
import xbmcvfs

from resources import lib
from resources.lib import playlist
from resources.lib.playlist import DIRECTORY, PLAYLIST, BgmSource

KOREAN_TRACK = "강허달림-기다림설레임.mp3"


def _touch(path: pathlib.Path, content: str = "x", mtime: float = 1000.0) -> str:
    """Create a real file with a controlled modification time."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.utime(str(path), (mtime, mtime))
    return str(path)


def _read_lines(path: str) -> List[str]:
    with open(path, encoding="utf-8") as handle:
        return handle.read().splitlines()


# -- scan_directory ----------------------------------------------------------


def test_scan_directory_collects_every_supported_extension(
    tmp_path: pathlib.Path,
) -> None:
    for name in ("a.mp3", "b.wav", "c.ogg", "d.wma", "e.flac", "f.aac", "g.m4a"):
        _touch(tmp_path / name)

    found = playlist.scan_directory(str(tmp_path))

    assert [os.path.basename(track) for track in found] == [
        "a.mp3",
        "b.wav",
        "c.ogg",
        "d.wma",
        "e.flac",
        "f.aac",
        "g.m4a",
    ]


def test_scan_directory_matches_extensions_case_insensitively(
    tmp_path: pathlib.Path,
) -> None:
    _touch(tmp_path / "loud.MP3")
    _touch(tmp_path / "quiet.FlAc")

    found = playlist.scan_directory(str(tmp_path))

    assert sorted(os.path.basename(track) for track in found) == [
        "loud.MP3",
        "quiet.FlAc",
    ]


def test_scan_directory_skips_unsupported_files(tmp_path: pathlib.Path) -> None:
    _touch(tmp_path / "keep.mp3")
    _touch(tmp_path / "cover.jpg")
    _touch(tmp_path / "notes.txt")
    _touch(tmp_path / "movie.mp4")

    found = playlist.scan_directory(str(tmp_path))

    assert [os.path.basename(track) for track in found] == ["keep.mp3"]


def test_scan_directory_recurses_into_subdirectories(tmp_path: pathlib.Path) -> None:
    _touch(tmp_path / "top.mp3")
    _touch(tmp_path / "jazz" / "deep" / "bottom.flac")

    found = playlist.scan_directory(str(tmp_path))

    assert sorted(os.path.basename(track) for track in found) == [
        "bottom.flac",
        "top.mp3",
    ]


def test_scan_directory_returns_absolute_paths(tmp_path: pathlib.Path) -> None:
    _touch(tmp_path / "jazz" / "tune.mp3")

    found = playlist.scan_directory(str(tmp_path))

    assert found == [str(tmp_path / "jazz" / "tune.mp3")]


def test_scan_directory_keeps_a_korean_filename_intact(tmp_path: pathlib.Path) -> None:
    _touch(tmp_path / KOREAN_TRACK)
    _touch(tmp_path / "café" / "piano.mp3")

    found = playlist.scan_directory(str(tmp_path))

    assert sorted(found) == sorted(
        [str(tmp_path / KOREAN_TRACK), str(tmp_path / "café" / "piano.mp3")]
    )


def test_scan_directory_of_an_empty_directory_finds_nothing(
    tmp_path: pathlib.Path,
) -> None:
    assert playlist.scan_directory(str(tmp_path)) == []


def test_scan_directory_of_a_missing_directory_finds_nothing(
    tmp_path: pathlib.Path,
) -> None:
    assert playlist.scan_directory(str(tmp_path / "gone")) == []


# -- write_m3u ---------------------------------------------------------------


def test_write_m3u_writes_one_path_per_line(tmp_path: pathlib.Path) -> None:
    destination = str(tmp_path / "bgm.m3u")

    playlist.write_m3u(["/music/a.mp3", "/music/b.flac"], destination)

    assert _read_lines(destination) == ["/music/a.mp3", "/music/b.flac"]


def test_write_m3u_round_trips_korean_paths_as_utf8(tmp_path: pathlib.Path) -> None:
    destination = str(tmp_path / "bgm.m3u")
    tracks = ["/음악/" + KOREAN_TRACK, "/音楽/ジャズ.flac"]

    playlist.write_m3u(tracks, destination)

    assert _read_lines(destination) == tracks


def test_write_m3u_overwrites_a_previous_generation(tmp_path: pathlib.Path) -> None:
    destination = _touch(tmp_path / "bgm.m3u", content="/music/stale.mp3\n")

    playlist.write_m3u(["/music/fresh.mp3"], destination)

    assert _read_lines(destination) == ["/music/fresh.mp3"]


def test_write_m3u_of_no_tracks_writes_an_empty_file(tmp_path: pathlib.Path) -> None:
    destination = str(tmp_path / "bgm.m3u")

    playlist.write_m3u([], destination)

    assert _read_lines(destination) == []


# -- write_m3u: failed and partial writes (D-009 second addendum) ------------


def _fail_write_after(monkeypatch: pytest.MonkeyPatch, successes: int) -> None:
    """Make the fake's ``File.write()`` return False after ``successes`` calls.

    Reproduces the real-Kodi failure mode D-009's second addendum records:
    ``write()`` returns ``False`` instead of raising, so a write that dies
    partway looks like a completed one to any caller that only watches for
    an exception.
    """
    real_write = xbmcvfs.File.write
    written: List[str] = []

    def counting_write(handle: Any, data: str) -> bool:
        written.append(data)
        if len(written) > successes:
            return False
        return bool(real_write(handle, data))

    monkeypatch.setattr(xbmcvfs.File, "write", counting_write)


def _partial_file_path(destination: str) -> str:
    """The sibling temp file write_m3u builds the new playlist in."""
    return destination + ".part"


def test_write_m3u_reports_success_when_every_line_was_written(
    tmp_path: pathlib.Path,
) -> None:
    destination = str(tmp_path / "bgm.m3u")

    assert playlist.write_m3u(["/music/a.mp3", "/music/b.flac"], destination) is True


def test_write_m3u_writes_exactly_one_newline_terminated_line_per_track(
    tmp_path: pathlib.Path,
) -> None:
    # Byte-level regression guard for the atomic-write rework: the file a
    # successful call leaves behind must be the same bytes it always was.
    destination = str(tmp_path / "bgm.m3u")

    playlist.write_m3u(["/music/a.mp3", "/music/b.flac"], destination)

    with open(destination, "rb") as handle:
        assert handle.read() == b"/music/a.mp3\n/music/b.flac\n"


def test_write_m3u_reports_failure_when_the_very_first_write_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A failed open surfaces this way, not as an exception: the fake -- like
    # real Kodi -- hands back a handle whose write() just returns False.
    destination = str(tmp_path / "bgm.m3u")
    _fail_write_after(monkeypatch, successes=0)

    assert playlist.write_m3u(["/music/a.mp3", "/music/b.flac"], destination) is False


def test_write_m3u_creates_no_destination_at_all_when_the_first_write_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = str(tmp_path / "bgm.m3u")
    _fail_write_after(monkeypatch, successes=0)

    playlist.write_m3u(["/music/a.mp3"], destination)

    assert not os.path.exists(destination)


def test_write_m3u_reports_failure_when_a_write_dies_partway_through(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = str(tmp_path / "bgm.m3u")
    tracks = ["/music/{0}.mp3".format(index) for index in range(5)]
    _fail_write_after(monkeypatch, successes=2)

    assert playlist.write_m3u(tracks, destination) is False


def test_write_m3u_reports_failure_when_a_write_lies_about_storing_it_all(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # D-009's lesson is that xbmcvfs mixes failure conventions, so a True
    # from write() is not proof on its own: the finished file is measured
    # before it is allowed to replace the previous generation.
    destination = _touch(
        tmp_path / "bgm.m3u", content="/music/good.mp3\n", mtime=1000.0
    )
    real_write = xbmcvfs.File.write

    def short_write(handle: Any, data: str) -> bool:
        real_write(handle, data[:4])
        return True

    monkeypatch.setattr(xbmcvfs.File, "write", short_write)

    assert playlist.write_m3u(["/music/a.mp3", "/music/b.mp3"], destination) is False
    assert _read_lines(destination) == ["/music/good.mp3"]
    assert os.path.getmtime(destination) == 1000.0


def test_write_m3u_reports_failure_when_the_backend_raises_instead_of_lying(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # xbmcvfs mixes both failure conventions (D-009), so the backends that
    # do raise must end the same way as the ones that return False: no
    # exception escaping into resolve(), previous playlist left alone.
    destination = _touch(
        tmp_path / "bgm.m3u", content="/music/good.mp3\n", mtime=1000.0
    )
    real_file = xbmcvfs.File

    def refuse_writes(target: str, mode: str = "r") -> Any:
        if mode == "w":
            raise OSError("read-only filesystem")
        return real_file(target, mode)

    monkeypatch.setattr(xbmcvfs, "File", refuse_writes)

    assert playlist.write_m3u(["/music/fresh.mp3"], destination) is False
    assert _read_lines(destination) == ["/music/good.mp3"]
    assert os.path.getmtime(destination) == 1000.0


def test_write_m3u_reports_failure_when_the_destination_cannot_be_opened(
    tmp_path: pathlib.Path,
) -> None:
    # An open that failed is invisible to the per-line check when there is no
    # line to write: nothing calls write(), so only the finished file's
    # absence gives it away.
    destination = str(tmp_path / "no-such-directory" / "bgm.m3u")

    assert playlist.write_m3u([], destination) is False


def test_write_m3u_leaves_the_previous_playlist_byte_identical_on_a_failure(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The damage a non-atomic write does: a truncated bgm.m3u would be served
    # as a real playlist, and _already_holds() would then read it back as the
    # list to keep, so both content and timestamp have to survive untouched.
    destination = _touch(
        tmp_path / "bgm.m3u", content="/music/good.mp3\n", mtime=1000.0
    )
    tracks = ["/music/{0}.mp3".format(index) for index in range(5)]
    _fail_write_after(monkeypatch, successes=2)

    playlist.write_m3u(tracks, destination)

    assert _read_lines(destination) == ["/music/good.mp3"]
    assert os.path.getmtime(destination) == 1000.0


def test_write_m3u_logs_an_error_naming_the_playlist_it_could_not_write(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = str(tmp_path / "bgm.m3u")
    _fail_write_after(monkeypatch, successes=1)

    playlist.write_m3u(["/music/a.mp3", "/music/b.mp3"], destination)

    assert any(destination in line for line in _error_logs())


def test_write_m3u_leaves_no_partial_file_behind_after_a_success(
    tmp_path: pathlib.Path,
) -> None:
    destination = str(tmp_path / "bgm.m3u")

    playlist.write_m3u(["/music/a.mp3"], destination)

    assert not os.path.exists(_partial_file_path(destination))


def test_write_m3u_leaves_no_partial_file_behind_after_a_failure(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = str(tmp_path / "bgm.m3u")
    _fail_write_after(monkeypatch, successes=1)

    playlist.write_m3u(["/music/a.mp3", "/music/b.mp3"], destination)

    assert not os.path.exists(_partial_file_path(destination))


def test_write_m3u_still_replaces_a_destination_when_rename_will_not_overwrite(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Kodi's rename() overwrite semantics are unverified across platforms, so
    # write_m3u must cope with a backend that refuses to rename onto an
    # existing file: delete the destination first, then rename again.
    destination = _touch(tmp_path / "bgm.m3u", content="/music/stale.mp3\n")
    real_rename = xbmcvfs.rename

    def refuse_to_overwrite(source: str, target: str) -> bool:
        if os.path.exists(target):
            return False
        return bool(real_rename(source, target))

    monkeypatch.setattr(xbmcvfs, "rename", refuse_to_overwrite)

    assert playlist.write_m3u(["/music/fresh.mp3"], destination) is True
    assert _read_lines(destination) == ["/music/fresh.mp3"]


def test_write_m3u_reports_failure_when_the_replacement_cannot_be_renamed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = _touch(
        tmp_path / "bgm.m3u", content="/music/good.mp3\n", mtime=1000.0
    )
    monkeypatch.setattr(xbmcvfs, "rename", lambda source, target: False)
    monkeypatch.setattr(xbmcvfs, "delete", lambda path: False)

    assert playlist.write_m3u(["/music/fresh.mp3"], destination) is False
    assert _read_lines(destination) == ["/music/good.mp3"]
    assert os.path.getmtime(destination) == 1000.0


# -- resolve -----------------------------------------------------------------


def test_resolve_returns_a_playlist_file_that_exists(tmp_path: pathlib.Path) -> None:
    my_m3u = _touch(tmp_path / "my.m3u", content="/music/a.mp3\n")

    assert playlist.resolve(BgmSource(kind=PLAYLIST, path=my_m3u)) == my_m3u


def test_resolve_rejects_a_missing_playlist_file(tmp_path: pathlib.Path) -> None:
    assert (
        playlist.resolve(BgmSource(kind=PLAYLIST, path=str(tmp_path / "gone.m3u")))
        is None
    )


def test_resolve_rejects_an_empty_playlist_file(tmp_path: pathlib.Path) -> None:
    empty = _touch(tmp_path / "empty.m3u", content="")

    assert playlist.resolve(BgmSource(kind=PLAYLIST, path=empty)) is None


def test_resolve_builds_the_profile_m3u_from_a_directory(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    music = tmp_path / "music"
    _touch(music / "a.mp3")
    _touch(music / "jazz" / "b.flac")

    resolved = playlist.resolve(BgmSource(kind=DIRECTORY, path=str(music)))

    assert resolved == str(tmp_path / "profile" / "bgm.m3u")
    assert _read_lines(str(resolved)) == [
        str(music / "a.mp3"),
        str(music / "jazz" / "b.flac"),
    ]


def test_resolve_writes_korean_track_paths_into_the_profile_m3u(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    music = tmp_path / "음악"
    _touch(music / KOREAN_TRACK)

    resolved = playlist.resolve(BgmSource(kind=DIRECTORY, path=str(music)))

    assert resolved is not None
    assert _read_lines(resolved) == [str(music / KOREAN_TRACK)]


def test_resolve_rejects_a_directory_holding_no_supported_audio(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    music = tmp_path / "music"
    _touch(music / "cover.jpg")

    assert playlist.resolve(BgmSource(kind=DIRECTORY, path=str(music))) is None


def test_resolve_rejects_a_missing_directory(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))

    assert (
        playlist.resolve(BgmSource(kind=DIRECTORY, path=str(tmp_path / "gone"))) is None
    )


def test_resolve_replaces_a_derived_m3u_left_over_from_another_source(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    _touch(profile / "bgm.m3u", content="/music/stale.mp3\n", mtime=1000.0)
    music = tmp_path / "music"
    _touch(music / "current.mp3")

    resolved = playlist.resolve(BgmSource(kind=DIRECTORY, path=str(music)))

    assert resolved is not None
    assert _read_lines(resolved) == [str(music / "current.mp3")]


# -- PlaylistFormat / supports_shuffle (FR-008, data-model.md) ---------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/music/mix.m3u", playlist.PlaylistFormat.M3U),
        ("/music/mix.m3u8", playlist.PlaylistFormat.M3U),
        ("/music/mix.pls", playlist.PlaylistFormat.PLS),
        ("/music/smart.xsp", playlist.PlaylistFormat.XSP),
    ],
)
def test_playlist_format_is_read_from_the_extension(
    path: str, expected: "playlist.PlaylistFormat"
) -> None:
    assert BgmSource(kind=PLAYLIST, path=path).playlist_format is expected


@pytest.mark.parametrize("extension", [".PLS", ".Pls", ".pLs"])
def test_playlist_format_reads_pls_whatever_the_extension_case(extension: str) -> None:
    # D-011's settings-UI `contains` heuristic may well be case-sensitive; the
    # runtime behavior FR-008 actually depends on must not be.
    source = BgmSource(kind=PLAYLIST, path="/music/mix" + extension)

    assert source.playlist_format is playlist.PlaylistFormat.PLS


@pytest.mark.parametrize("extension", [".XSP", ".Xsp", ".xSp"])
def test_playlist_format_reads_xsp_whatever_the_extension_case(extension: str) -> None:
    source = BgmSource(kind=PLAYLIST, path="/music/smart" + extension)

    assert source.playlist_format is playlist.PlaylistFormat.XSP


def test_playlist_format_reads_a_korean_pls_path() -> None:
    source = BgmSource(kind=PLAYLIST, path="/음악/재즈/좋아하는-곡.pls")

    assert source.playlist_format is playlist.PlaylistFormat.PLS


@pytest.mark.parametrize("path", ["/music/mix", "/music/mix.txt", ""])
def test_playlist_format_falls_back_to_m3u_for_anything_unrecognized(
    path: str,
) -> None:
    # FR-007's extension set is enforced by the settings <masking>; anything
    # that slips past it is treated as shuffle-able, since FR-008 only ever
    # carves out .pls and .xsp.
    assert BgmSource(kind=PLAYLIST, path=path).playlist_format is (
        playlist.PlaylistFormat.M3U
    )


def test_a_directory_source_is_the_m3u_it_derives_whatever_it_is_named() -> None:
    # The derived bgm.m3u is what actually gets played, so a directory that
    # happens to be named like a playlist is still an M3U source.
    source = BgmSource(kind=DIRECTORY, path="/music/my.pls")

    assert source.playlist_format is playlist.PlaylistFormat.M3U


@pytest.mark.parametrize(
    "kind,path,expected",
    [
        (DIRECTORY, "/music/jazz", True),
        (DIRECTORY, "/music/my.xsp", True),
        (PLAYLIST, "/music/mix.m3u", True),
        (PLAYLIST, "/music/mix.M3U", True),
        (PLAYLIST, "/music/mix.pls", False),
        (PLAYLIST, "/music/mix.PLS", False),
        (PLAYLIST, "/music/smart.xsp", False),
        (PLAYLIST, "/music/smart.XSP", False),
    ],
)
def test_supports_shuffle_is_false_only_for_pls_and_xsp(
    kind: "playlist.SourceKind", path: str, expected: bool
) -> None:
    # FR-008: .pls and .xsp play in their own native order.
    assert BgmSource(kind=kind, path=path).supports_shuffle is expected


# -- parse_pls -----------------------------------------------------------


def _error_logs() -> List[str]:
    return [
        message for message, level in xbmc.world.log_lines if level == xbmc.LOGERROR
    ]


def _warning_logs() -> List[str]:
    return [
        message for message, level in xbmc.world.log_lines if level == xbmc.LOGWARNING
    ]


def _debug_logs() -> List[str]:
    return [
        message for message, level in xbmc.world.log_lines if level == xbmc.LOGDEBUG
    ]


def test_parse_pls_returns_tracks_in_ascending_index_order(
    tmp_path: pathlib.Path,
) -> None:
    track_a = _touch(tmp_path / "a.mp3")
    track_b = _touch(tmp_path / "b.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nFile2={0}\nFile1={1}\nNumberOfEntries=2\nVersion=2\n".format(
            track_b, track_a
        ),
    )

    assert playlist.parse_pls(pls) == [track_a, track_b]


def test_parse_pls_reads_the_file_key_case_insensitively(
    tmp_path: pathlib.Path,
) -> None:
    track_a = _touch(tmp_path / "a.mp3")
    track_b = _touch(tmp_path / "b.mp3")
    track_c = _touch(tmp_path / "c.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nfile1={0}\nFILE2={1}\nFiLe3={2}\n".format(
            track_a, track_b, track_c
        ),
    )

    assert playlist.parse_pls(pls) == [track_a, track_b, track_c]


def test_parse_pls_resolves_a_relative_path_against_its_own_directory(
    tmp_path: pathlib.Path,
) -> None:
    _touch(tmp_path / "bgm-source" / "track.mp3")
    pls = _touch(
        tmp_path / "playlists" / "mix.pls",
        "[playlist]\nFile1=../bgm-source/track.mp3\n",
    )

    assert playlist.parse_pls(pls) == [
        str(tmp_path / "playlists" / ".." / "bgm-source" / "track.mp3")
    ]


def test_parse_pls_leaves_an_absolute_path_alone(tmp_path: pathlib.Path) -> None:
    track = _touch(tmp_path / "absolute" / "track.mp3")
    pls = _touch(tmp_path / "mix.pls", "[playlist]\nFile1={0}\n".format(track))

    assert playlist.parse_pls(pls) == [track]


def test_parse_pls_leaves_a_special_path_alone_when_it_exists(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        xbmcvfs.SPECIAL_ROOTS, "profile", str(tmp_path / "profile") + "/"
    )
    _touch(tmp_path / "profile" / "addon_data" / "x" / "track.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nFile1=special://profile/addon_data/x/track.mp3\n",
    )

    assert playlist.parse_pls(pls) == ["special://profile/addon_data/x/track.mp3"]


def test_parse_pls_leaves_a_url_path_alone(tmp_path: pathlib.Path) -> None:
    # A remote http:// entry has no local file for the existence check to
    # inspect; the fake xbmcvfs makes no real network call and treats any
    # such scheme as existing (tests/fakes/xbmcvfs.py's exists()), which
    # keeps this test about _resolve_pls_path leaving the value unrewritten
    # -- a separate concern from whether the file exists.
    pls = _touch(
        tmp_path / "mix.pls", "[playlist]\nFile1=http://example.com/track.mp3\n"
    )

    assert playlist.parse_pls(pls) == ["http://example.com/track.mp3"]


def test_parse_pls_skips_an_empty_file_entry(tmp_path: pathlib.Path) -> None:
    track_a = _touch(tmp_path / "a.mp3")
    track_c = _touch(tmp_path / "c.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nFile1={0}\nFile2=\nFile3={1}\n".format(track_a, track_c),
    )

    assert playlist.parse_pls(pls) == [track_a, track_c]


def test_parse_pls_tolerates_gaps_and_uses_the_actually_scanned_entries(
    tmp_path: pathlib.Path,
) -> None:
    track_a = _touch(tmp_path / "a.mp3")
    track_b = _touch(tmp_path / "b.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nFile1={0}\nFile5={1}\n".format(track_a, track_b),
    )

    assert playlist.parse_pls(pls) == [track_a, track_b]


def test_parse_pls_logs_a_warning_on_a_numberofentries_mismatch_but_still_resolves(
    tmp_path: pathlib.Path,
) -> None:
    track_a = _touch(tmp_path / "a.mp3")
    track_b = _touch(tmp_path / "b.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nNumberOfEntries=5\nFile1={0}\nFile2={1}\n".format(
            track_a, track_b
        ),
    )

    tracks = playlist.parse_pls(pls)

    assert tracks == [track_a, track_b]
    assert _warning_logs() != []


def test_parse_pls_logs_no_warning_when_numberofentries_matches(
    tmp_path: pathlib.Path,
) -> None:
    track_a = _touch(tmp_path / "a.mp3")
    track_b = _touch(tmp_path / "b.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nNumberOfEntries=2\nFile1={0}\nFile2={1}\n".format(
            track_a, track_b
        ),
    )

    playlist.parse_pls(pls)

    assert _warning_logs() == []


def test_parse_pls_without_a_playlist_header_returns_empty_and_logs_an_error(
    tmp_path: pathlib.Path,
) -> None:
    track = _touch(tmp_path / "a.mp3")
    pls = _touch(tmp_path / "mix.pls", "File1={0}\n".format(track))

    assert playlist.parse_pls(pls) == []
    assert _error_logs() != []


def test_parse_pls_of_an_unreadable_file_returns_empty_and_logs_an_error(
    tmp_path: pathlib.Path,
) -> None:
    assert playlist.parse_pls(str(tmp_path / "missing.pls")) == []
    assert _error_logs() != []


# -- parse_pls: existence filtering ------------------------------------------


def test_parse_pls_excludes_an_entry_whose_file_does_not_exist(
    tmp_path: pathlib.Path,
) -> None:
    track_a = _touch(tmp_path / "a.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nFile1={0}\nFile2={1}\n".format(track_a, tmp_path / "gone.mp3"),
    )

    assert playlist.parse_pls(pls) == [track_a]


def test_parse_pls_keeps_only_existing_entries_in_ascending_order(
    tmp_path: pathlib.Path,
) -> None:
    track_a = _touch(tmp_path / "a.mp3")
    track_c = _touch(tmp_path / "c.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nFile1={0}\nFile2={1}\nFile3={2}\n".format(
            track_a, tmp_path / "gone.mp3", track_c
        ),
    )

    assert playlist.parse_pls(pls) == [track_a, track_c]


def test_parse_pls_returns_empty_when_every_entry_is_missing(
    tmp_path: pathlib.Path,
) -> None:
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nFile1={0}\nFile2={1}\n".format(
            tmp_path / "gone-1.mp3", tmp_path / "gone-2.mp3"
        ),
    )

    assert playlist.parse_pls(pls) == []


def test_parse_pls_logs_a_warning_when_an_entry_is_missing(
    tmp_path: pathlib.Path,
) -> None:
    track_a = _touch(tmp_path / "a.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nFile1={0}\nFile2={1}\n".format(track_a, tmp_path / "gone.mp3"),
    )

    playlist.parse_pls(pls)

    assert _warning_logs() != []


def test_parse_pls_logs_no_warning_when_every_entry_exists(
    tmp_path: pathlib.Path,
) -> None:
    track_a = _touch(tmp_path / "a.mp3")
    track_b = _touch(tmp_path / "b.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nFile1={0}\nFile2={1}\n".format(track_a, track_b),
    )

    playlist.parse_pls(pls)

    assert _warning_logs() == []


def test_parse_pls_missing_file_warning_is_independent_of_the_count_mismatch_warning(
    tmp_path: pathlib.Path,
) -> None:
    # NumberOfEntries correctly matches the actually-parsed entry count (2),
    # so only the existence warning should fire -- not the mismatch one.
    track_a = _touch(tmp_path / "a.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nNumberOfEntries=2\nFile1={0}\nFile2={1}\n".format(
            track_a, tmp_path / "gone.mp3"
        ),
    )

    playlist.parse_pls(pls)

    warnings = _warning_logs()
    assert len(warnings) == 1
    assert "does not match" not in warnings[0]


def test_numberofentries_mismatch_warning_is_independent_of_the_missing_file_warning(
    tmp_path: pathlib.Path,
) -> None:
    # Every referenced file exists, so only the NumberOfEntries mismatch
    # warning should fire -- not the existence one.
    track_a = _touch(tmp_path / "a.mp3")
    track_b = _touch(tmp_path / "b.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nNumberOfEntries=5\nFile1={0}\nFile2={1}\n".format(
            track_a, track_b
        ),
    )

    playlist.parse_pls(pls)

    warnings = _warning_logs()
    assert len(warnings) == 1
    assert "does not match" in warnings[0]


# -- resolve_xsp -----------------------------------------------------------


def test_resolve_xsp_returns_every_file_entry_from_a_single_page() -> None:
    xbmc.world.xsp_directories["/music/smart.xsp"] = [
        {"file": "/music/a.mp3", "filetype": "file"},
        {"file": "/music/b.mp3", "filetype": "file"},
    ]

    assert playlist.resolve_xsp("/music/smart.xsp") == [
        "/music/a.mp3",
        "/music/b.mp3",
    ]


def test_resolve_xsp_never_requests_filetype_as_a_property() -> None:
    # Real-device (T041) finding: "filetype" is always in Files.GetDirectory's
    # response already (Kodi's List.Item.File schema marks it required), but
    # it is not a valid *requestable* value in List.Fields.Files' enum --
    # asking for it makes Kodi reject the whole call with a schema error.
    xbmc.world.xsp_directories["/music/smart.xsp"] = [
        {"file": "/music/a.mp3", "filetype": "file"},
    ]

    playlist.resolve_xsp("/music/smart.xsp")

    assert xbmc.world.get_directory_calls[0]["properties"] == ["file"]


def test_resolve_xsp_excludes_entries_that_are_not_files() -> None:
    xbmc.world.xsp_directories["/music/smart.xsp"] = [
        {"file": "/music/a.mp3", "filetype": "file"},
        {"file": "/music/sub", "filetype": "directory"},
    ]

    assert playlist.resolve_xsp("/music/smart.xsp") == ["/music/a.mp3"]


def test_resolve_xsp_pages_through_a_result_larger_than_one_page() -> None:
    tracks = ["/music/track{0}.mp3".format(i) for i in range(1500)]
    xbmc.world.xsp_directories["/music/smart.xsp"] = [
        {"file": track, "filetype": "file"} for track in tracks
    ]

    assert playlist.resolve_xsp("/music/smart.xsp") == tracks
    assert len(xbmc.world.get_directory_calls) == 2


def test_resolve_xsp_returns_empty_and_logs_error_on_a_json_rpc_error_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        xbmc,
        "executeJSONRPC",
        lambda request: (
            '{"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "boom"}}'
        ),
    )

    assert playlist.resolve_xsp("/music/smart.xsp") == []
    assert _error_logs() != []


def test_resolve_xsp_returns_empty_and_logs_error_on_a_malformed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(xbmc, "executeJSONRPC", lambda request: "not json")

    assert playlist.resolve_xsp("/music/smart.xsp") == []
    assert _error_logs() != []


def test_resolve_xsp_rewrites_a_musicplaylists_path_to_its_special_form(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Real-device (R-8) finding: Files.GetDirectory rejects an arbitrary
    # absolute path with "Invalid params" (Kodi's own RemoteAccessAllowed
    # only allows special:// roots or a registered, shareable source) -- even
    # one pointing at Kodi's own default smart-playlist save location, since
    # the settings file-browse dialog already resolves it down to a plain
    # absolute path before the addon ever sees it. resolve_xsp must undo that
    # resolution before calling Kodi. Deliberately keyed off
    # special://profile/, not special://musicplaylists/ -- a second
    # real-device finding showed the latter translates to a multipath://
    # union of two real directories, never a single one this rewrite could
    # prefix-match against.
    profile_root = str(tmp_path / "profile") + "/"
    monkeypatch.setitem(xbmcvfs.SPECIAL_ROOTS, "profile", profile_root)
    playlists_root = profile_root + "playlists/music/"
    xbmc.world.xsp_directories["special://profile/playlists/music/sample.xsp"] = [
        {"file": "/music/a.mp3", "filetype": "file"},
    ]

    tracks = playlist.resolve_xsp(playlists_root + "sample.xsp")

    assert tracks == ["/music/a.mp3"]
    assert (
        xbmc.world.get_directory_calls[0]["directory"]
        == "special://profile/playlists/music/sample.xsp"
    )


def test_resolve_xsp_leaves_a_path_outside_musicplaylists_alone(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        xbmcvfs.SPECIAL_ROOTS, "profile", str(tmp_path / "profile") + "/"
    )
    xbmc.world.xsp_directories["/elsewhere/sample.xsp"] = [
        {"file": "/music/a.mp3", "filetype": "file"},
    ]

    playlist.resolve_xsp("/elsewhere/sample.xsp")

    assert xbmc.world.get_directory_calls[0]["directory"] == "/elsewhere/sample.xsp"


# -- is_music_smartplaylist --------------------------------------------------


def test_is_music_smartplaylist_accepts_a_songs_playlist(
    tmp_path: pathlib.Path,
) -> None:
    xsp = _touch(tmp_path / "smart.xsp", '<smartplaylist type="songs"/>')

    assert playlist.is_music_smartplaylist(xsp) is True


def test_is_music_smartplaylist_accepts_the_legacy_music_type(
    tmp_path: pathlib.Path,
) -> None:
    # Kodi itself normalizes type="music" to "songs"
    # (CSmartPlaylist::readName(), xbmc/playlists/SmartPlayList.cpp).
    xsp = _touch(tmp_path / "smart.xsp", '<smartplaylist type="music"/>')

    assert playlist.is_music_smartplaylist(xsp) is True


def test_is_music_smartplaylist_accepts_a_songs_playlist_with_real_content(
    tmp_path: pathlib.Path,
) -> None:
    xsp = _touch(
        tmp_path / "smart.xsp",
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        '<smartplaylist type="songs">\n'
        "    <name>배경음악</name>\n"
        "    <match>all</match>\n"
        '    <rule field="genre" operator="is"><value>재즈</value></rule>\n'
        "</smartplaylist>\n",
    )

    assert playlist.is_music_smartplaylist(xsp) is True


@pytest.mark.parametrize(
    "kind", ["movies", "musicvideos", "mixed", "albums", "artists", "episodes"]
)
def test_is_music_smartplaylist_rejects_every_non_song_type(
    kind: str, tmp_path: pathlib.Path
) -> None:
    xsp = _touch(tmp_path / "smart.xsp", '<smartplaylist type="{0}"/>'.format(kind))

    assert playlist.is_music_smartplaylist(xsp) is False


def test_is_music_smartplaylist_rejects_a_playlist_with_no_type_attribute(
    tmp_path: pathlib.Path,
) -> None:
    xsp = _touch(tmp_path / "smart.xsp", "<smartplaylist/>")

    assert playlist.is_music_smartplaylist(xsp) is False


def test_is_music_smartplaylist_rejects_a_file_that_is_not_valid_xml(
    tmp_path: pathlib.Path,
) -> None:
    xsp = _touch(tmp_path / "smart.xsp", "<smartplaylist type='songs'")

    assert playlist.is_music_smartplaylist(xsp) is False
    assert _error_logs() != []


def test_is_music_smartplaylist_rejects_a_file_rooted_at_another_element(
    tmp_path: pathlib.Path,
) -> None:
    xsp = _touch(tmp_path / "smart.xsp", "<settings><type>songs</type></settings>")

    assert playlist.is_music_smartplaylist(xsp) is False
    assert any("settings" in message for message in _error_logs())


def test_is_music_smartplaylist_logs_a_warning_naming_the_type_it_found(
    tmp_path: pathlib.Path,
) -> None:
    xsp = _touch(tmp_path / "smart.xsp", '<smartplaylist type="movies"/>')

    playlist.is_music_smartplaylist(xsp)

    warnings = _warning_logs()
    assert len(warnings) == 1
    assert "movies" in warnings[0]
    assert xsp in warnings[0]
    assert _error_logs() == []


def test_is_music_smartplaylist_rejects_a_missing_file_without_raising(
    tmp_path: pathlib.Path,
) -> None:
    assert playlist.is_music_smartplaylist(str(tmp_path / "gone.xsp")) is False
    assert _error_logs() != []


def test_is_music_smartplaylist_rejects_an_empty_file(
    tmp_path: pathlib.Path,
) -> None:
    xsp = _touch(tmp_path / "smart.xsp", "")

    assert playlist.is_music_smartplaylist(xsp) is False
    assert _error_logs() != []


def test_is_music_smartplaylist_logs_nothing_for_a_music_playlist(
    tmp_path: pathlib.Path,
) -> None:
    xsp = _touch(tmp_path / "smart.xsp", '<smartplaylist type="songs"/>')

    playlist.is_music_smartplaylist(xsp)

    assert _error_logs() == []
    assert _warning_logs() == []


def test_is_music_smartplaylist_reads_a_korean_path(tmp_path: pathlib.Path) -> None:
    xsp = _touch(tmp_path / "음악" / "재즈.xsp", '<smartplaylist type="songs"/>')

    assert playlist.is_music_smartplaylist(xsp) is True


# -- resolve() for .pls / .xsp sources ----------------------------------------


def test_resolve_builds_the_profile_m3u_from_a_pls_source(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    track_a = _touch(tmp_path / "a.mp3")
    track_b = _touch(tmp_path / "b.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nFile1={0}\nFile2={1}\n".format(track_a, track_b),
    )

    resolved = playlist.resolve(BgmSource(kind=PLAYLIST, path=pls))

    assert resolved == str(tmp_path / "profile" / "bgm.m3u")
    assert _read_lines(str(resolved)) == [track_a, track_b]


def test_resolve_builds_the_profile_m3u_from_an_xsp_source(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    xsp = str(tmp_path / "smart.xsp")
    xbmc.world.xsp_directories[xsp] = [
        {"file": "/music/a.mp3", "filetype": "file"},
        {"file": "/music/b.mp3", "filetype": "file"},
    ]

    resolved = playlist.resolve(BgmSource(kind=PLAYLIST, path=xsp))

    assert resolved == str(tmp_path / "profile" / "bgm.m3u")
    assert _read_lines(str(resolved)) == ["/music/a.mp3", "/music/b.mp3"]


def test_resolve_rejects_a_pls_source_with_no_valid_entries(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    pls = _touch(tmp_path / "mix.pls", "[playlist]\n")

    assert playlist.resolve(BgmSource(kind=PLAYLIST, path=pls)) is None


def test_resolve_rejects_an_xsp_source_whose_json_rpc_call_errors(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    xsp = str(tmp_path / "smart.xsp")
    monkeypatch.setattr(
        xbmc,
        "executeJSONRPC",
        lambda request: '{"jsonrpc": "2.0", "id": 1, "error": {"code": -1}}',
    )

    assert playlist.resolve(BgmSource(kind=PLAYLIST, path=xsp)) is None


def test_resolve_leaves_a_stale_m3u_untouched_when_regeneration_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A real-device observation: the source is re-resolved on every start, but
    # if it fails to resolve (here: an .xsp's JSON-RPC call erroring),
    # _regenerate() must never touch bgm.m3u -- the
    # previous session's derived playlist stays exactly as it was, and this
    # session simply gets no BGM (FR-010), rather than an emptied or
    # partially-overwritten file.
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    _touch(profile / "settings.xml", mtime=2000.0)
    _touch(profile / "bgm.m3u", content="/music/stale.mp3\n", mtime=1000.0)
    monkeypatch.setattr(
        xbmc,
        "executeJSONRPC",
        lambda request: '{"jsonrpc": "2.0", "id": 1, "error": {"code": -1}}',
    )
    xsp = str(tmp_path / "smart.xsp")

    resolved = playlist.resolve(BgmSource(kind=PLAYLIST, path=xsp))

    assert resolved is None
    assert _read_lines(str(profile / "bgm.m3u")) == ["/music/stale.mp3"]


def test_resolve_leaves_the_cached_m3u_untouched_when_the_rewrite_fails_partway(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The sibling of the test above, for the failure D-009's second addendum
    # warns about: the new track list resolves fine, but writing it out dies
    # partway. A truncated bgm.m3u would be handed to PlayMedia as if it were
    # the whole playlist, so the
    # previous playlist must survive with its original content *and* mtime,
    # and this session must simply get no BGM (FR-010).
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    _touch(profile / "settings.xml", mtime=2000.0)
    _touch(profile / "bgm.m3u", content="/music/previous.mp3\n", mtime=1000.0)
    music = tmp_path / "music"
    for index in range(5):
        _touch(music / "{0}.mp3".format(index))
    _fail_write_after(monkeypatch, successes=2)

    resolved = playlist.resolve(BgmSource(kind=DIRECTORY, path=str(music)))

    assert resolved is None
    assert _read_lines(str(profile / "bgm.m3u")) == ["/music/previous.mp3"]
    assert os.path.getmtime(str(profile / "bgm.m3u")) == 1000.0
    assert any(str(profile / "bgm.m3u") in line for line in _error_logs())


def test_resolve_leaves_no_partial_file_in_the_profile_when_a_rewrite_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    _touch(profile / "settings.xml", mtime=2000.0)
    _touch(profile / "bgm.m3u", content="/music/previous.mp3\n", mtime=1000.0)
    music = tmp_path / "music"
    for index in range(5):
        _touch(music / "{0}.mp3".format(index))
    _fail_write_after(monkeypatch, successes=2)

    playlist.resolve(BgmSource(kind=DIRECTORY, path=str(music)))

    assert not os.path.exists(_partial_file_path(str(profile / "bgm.m3u")))


# -- .xsp is a live query: never cached across calls --------------------------


def test_resolve_re_runs_the_xsp_query_on_every_call(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    _touch(profile / "settings.xml", mtime=1000.0)
    xsp = str(tmp_path / "smart.xsp")
    xbmc.world.xsp_directories[xsp] = [{"file": "/music/a.mp3", "filetype": "file"}]
    source = BgmSource(kind=PLAYLIST, path=xsp)

    playlist.resolve(source)
    playlist.resolve(source)

    assert [call["directory"] for call in xbmc.world.get_directory_calls] == [xsp, xsp]


def test_resolve_picks_up_a_track_added_to_the_library_since_the_last_xsp_run(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    _touch(profile / "settings.xml", mtime=1000.0)
    xsp = str(tmp_path / "smart.xsp")
    xbmc.world.xsp_directories[xsp] = [{"file": "/music/a.mp3", "filetype": "file"}]
    source = BgmSource(kind=PLAYLIST, path=xsp)
    playlist.resolve(source)

    xbmc.world.xsp_directories[xsp] = [
        {"file": "/music/a.mp3", "filetype": "file"},
        {"file": "/music/newly-ripped.mp3", "filetype": "file"},
    ]
    resolved = playlist.resolve(source)

    assert resolved is not None
    assert _read_lines(resolved) == ["/music/a.mp3", "/music/newly-ripped.mp3"]


# -- .pls is a plain file the user can edit behind the addon's back -----------


def test_resolve_gives_up_when_the_pls_vanished_and_leaves_the_old_m3u_alone(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A .pls deleted between config.validate and resolve used to be covered by
    # the cache: an unstattable source forced no rebuild, so the previous
    # bgm.m3u kept playing. Re-resolving every start means this session simply
    # gets no BGM instead (FR-010) -- but the file it could not rebuild is
    # still left exactly as it was, so a restored .pls plays again next time.
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    _touch(profile / "bgm.m3u", content="/music/previous.mp3\n", mtime=1000.0)

    resolved = playlist.resolve(
        BgmSource(kind=PLAYLIST, path=str(tmp_path / "gone.pls"))
    )

    assert resolved is None
    assert _read_lines(str(profile / "bgm.m3u")) == ["/music/previous.mp3"]
    assert os.path.getmtime(str(profile / "bgm.m3u")) == 1000.0


# -- every derived source is re-resolved on every start (D-009, 2026-09-15) ---


class _FakeClock:
    """Stands in for the ``time`` module with readings the test supplies."""

    def __init__(self, readings: List[float]) -> None:
        self._readings = list(readings)

    def monotonic(self) -> float:
        if len(self._readings) > 1:
            return self._readings.pop(0)
        return self._readings[0]


def test_resolve_picks_up_a_track_added_to_the_directory_since_the_last_start(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # SC-005, and the exact inversion of what D-009's mtime cache used to pin:
    # a newly ripped album now appears in the derived playlist on the very next
    # slideshow. Nothing here touches settings.xml on purpose -- a settings
    # change was the only thing that used to force a directory rescan, so a
    # user whose library grew had no way to get their new music played.
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    music = tmp_path / "music"
    _touch(music / "a.mp3")
    source = BgmSource(kind=DIRECTORY, path=str(music))
    playlist.resolve(source)

    _touch(music / "newly-ripped.mp3")
    resolved = playlist.resolve(source)

    assert resolved is not None
    assert _read_lines(resolved) == [
        str(music / "a.mp3"),
        str(music / "newly-ripped.mp3"),
    ]


def test_resolve_does_not_rewrite_the_m3u_when_the_track_list_is_unchanged(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # What keeps re-resolving on every start cheap: the freshly derived list
    # is compared against what bgm.m3u already holds, and an identical one is
    # left alone -- file and mtime both. The mtime is the assertion because it
    # is the only externally visible proof that no write happened at all.
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    music = tmp_path / "music"
    _touch(music / "a.mp3")
    source = BgmSource(kind=DIRECTORY, path=str(music))
    first = playlist.resolve(source)
    assert first is not None
    os.utime(first, (1000.0, 1000.0))

    second = playlist.resolve(source)

    assert second == first
    assert os.path.getmtime(first) == 1000.0


def test_resolve_rewrites_the_m3u_when_the_track_list_changed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other half of that comparison: skipping the write must never be so
    # eager that a real change stops reaching bgm.m3u.
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    music = tmp_path / "music"
    _touch(music / "a.mp3")
    source = BgmSource(kind=DIRECTORY, path=str(music))
    first = playlist.resolve(source)
    assert first is not None
    os.utime(first, (1000.0, 1000.0))

    _touch(music / "b.mp3")
    playlist.resolve(source)

    assert os.path.getmtime(first) != 1000.0
    assert _read_lines(first) == [str(music / "a.mp3"), str(music / "b.mp3")]


def test_resolve_picks_up_an_edit_to_the_pls_that_preserved_its_mtime(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Edited without moving the .pls's own mtime (a restored backup, `rsync
    # -t`) -- the one edit the old mtime comparison was known to miss.
    # Re-parsing on every start catches it for free. Korean throughout: every
    # read on this path goes through xbmcvfs for D-009's encoding reason.
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    music = tmp_path / "음악"
    track_a = _touch(music / KOREAN_TRACK)
    track_b = _touch(music / "재즈.flac")
    pls = _touch(
        music / "목록.pls", "[playlist]\nFile1={0}\n".format(track_a), mtime=1000.0
    )
    source = BgmSource(kind=PLAYLIST, path=pls)
    playlist.resolve(source)

    _touch(
        music / "목록.pls",
        "[playlist]\nFile1={0}\nFile2={1}\n".format(track_a, track_b),
        mtime=1000.0,
    )
    resolved = playlist.resolve(source)

    assert resolved is not None
    assert _read_lines(resolved) == [track_a, track_b]


def test_resolve_rewrites_the_m3u_when_the_pls_only_reordered_its_entries(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FR-008: a .pls plays in its own native order, so the same tracks in a
    # different order is a real change. The comparison that skips the write
    # has to be an ordered one -- a set would silently keep playing the old
    # order forever.
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    track_a = _touch(tmp_path / "a.mp3")
    track_b = _touch(tmp_path / "b.mp3")
    pls = _touch(
        tmp_path / "mix.pls",
        "[playlist]\nFile1={0}\nFile2={1}\n".format(track_a, track_b),
    )
    source = BgmSource(kind=PLAYLIST, path=pls)
    resolved = playlist.resolve(source)
    assert resolved is not None

    _touch(
        tmp_path / "mix.pls",
        "[playlist]\nFile1={0}\nFile2={1}\n".format(track_b, track_a),
    )
    playlist.resolve(source)

    assert _read_lines(resolved) == [track_b, track_a]


def test_resolve_logs_how_long_a_source_took_even_when_it_yielded_no_tracks(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The slow-and-empty case is the one most worth seeing in kodi.log: a
    # misconfigured source on a slow share looks identical to a fast one in
    # the error line alone. Timing therefore has to be reported before the
    # no-tracks bail-out, not after it.
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    music = tmp_path / "music"
    _touch(music / "cover.jpg")

    playlist.resolve(BgmSource(kind=DIRECTORY, path=str(music)))

    logged = [message for message in _debug_logs() if str(music) in message]
    assert len(logged) == 1
    assert "0 tracks" in logged[0]


def test_resolve_logs_how_long_deriving_the_track_list_took(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The walk measurements that justified dropping the cache are synthetic and
    # from one machine; this line is how a genuinely slow real-world source
    # becomes visible in kodi.log instead of being guessed at. The clock is
    # driven by hand so the expected figure is derived here rather than read
    # back out of the code: 1.5 s between readings is 1500.0 *ms*, not 1.5.
    profile = tmp_path / "profile"
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    music = tmp_path / "music"
    _touch(music / "a.mp3")
    _touch(music / "b.mp3")
    monkeypatch.setattr(playlist, "time", _FakeClock([10.0, 11.5]))

    playlist.resolve(BgmSource(kind=DIRECTORY, path=str(music)))

    logged = [message for message in _debug_logs() if str(music) in message]
    assert len(logged) == 1
    assert "2 tracks" in logged[0]
    assert "1500.0 ms" in logged[0]
