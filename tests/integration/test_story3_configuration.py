"""User Story 3 -- the user configures where background music comes from.

Covers spec.md US3 acceptance scenarios 1-5 and quickstart.md's Tier 1
story-level rows for US3: FR-005 (either source kind is configurable), FR-006
(a directory is scanned recursively for the supported extension set), FR-007
(``.m3u``/``.pls``/``.xsp`` are all accepted as literal playlist sources),
FR-008 (shuffle is honored for a directory or ``.m3u`` source and ignored for
``.pls``/``.xsp``) and FR-014 (what a slideshow does about audio Kodi is
already playing).

One thing is worth naming about what is *not* tested here: D-011's
settings-screen grey-out of the ``random`` toggle is cosmetic, declared in
``settings.xml``; the rule FR-008 actually depends on is enforced in
``config.read_source`` and is what scenario 4 below exercises.

This addon still never parses a plain ``.m3u``'s contents -- Kodi's own
``PlayMedia`` does -- so an ``.m3u`` fixture below is plain non-empty text.
``.pls``/``.xsp`` are different: real-device testing found Kodi's own
``playoffset`` resume never advances past track 1 for these two formats, so
the addon resolves them itself (``playlist.parse_pls``/``resolve_xsp``) into a
derived ``bgm.m3u`` before ``PlayMedia`` ever sees them, which is why their
fixtures below carry real, minimal syntax instead of opaque text.

Everything drives the real ``session``/``config``/``playlist``/``player``/
``fader`` modules against the in-repo Kodi fakes (research.md D-008). The only
thing mocked out is FR-013's 1-second fade duration, shrunk to keep the suite
fast -- the ramp itself is the real one, on a real daemon thread.
"""

import pathlib
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import pytest
import xbmc
import xbmcaddon

from resources import lib
from resources.lib import fader, messages
from resources.lib.fader import Direction
from resources.lib.session import SessionState, SlideshowSession

world = xbmc.world
store = xbmcaddon.store

#: Ramp time actually run in tests; production asks for FR-013's 1000 ms.
FAST_MS = 40
FADE_DURATION_MS = 1000
JOIN_SECONDS = 2.0

#: D-009: a non-ASCII name has to survive the bytes-walk and the UTF-8
#: playlist round-trip, so every directory fixture carries one.
KOREAN_TRACK = "강허달림-기다림설레임.mp3"
KOREAN_DIRECTORY = "음악"

OTHER_MUSIC = "/music/someone-elses-album.mp3"

RANDOM_ON = "PlayerControl(RandomOn)"
RANDOM_OFF = "PlayerControl(RandomOff)"


# -- fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def fade_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[List[Tuple[Direction, int, int]]]:
    """Record what production asked ``fader.fade`` for, ramp it fast anyway.

    Keeps the real fader (real thread, real SetVolume builtins) in the loop
    while a whole test file's worth of 1-second ramps stays under a second.
    """
    requested: List[Tuple[Direction, int, int]] = []
    real_fade = fader.fade

    def quick(
        direction: Direction, baseline: int, duration_ms: int = FADE_DURATION_MS
    ) -> None:
        requested.append((direction, baseline, duration_ms))
        real_fade(direction, baseline, FAST_MS)

    monkeypatch.setattr(fader, "fade", quick)
    yield requested
    fader.cancel()
    fader.join(JOIN_SECONDS)


# -- source helpers ----------------------------------------------------------


def _configure_playlist_file(
    tmp_path: pathlib.Path,
    name: str,
    monkeypatch: pytest.MonkeyPatch,
    content: str = "/music/a.mp3\n",
) -> str:
    """Configure a real BGM playlist source of whatever extension.

    ``.m3u`` stays a literal pass-through -- Kodi's own ``PlayMedia`` reads
    it, so the addon never looks inside and ``content`` is only ever checked
    for non-emptiness (FR-010). ``.pls``/``.xsp`` are resolved by the addon
    itself before ``PlayMedia`` ever sees them, so a non-empty ``content``
    instead produces one real, resolvable track of that format -- for
    ``.pls`` specifically, ``parse_pls`` now also requires the referenced
    file to actually exist, so its entry points at a real file touched under
    ``tmp_path`` rather than ``content`` taken literally.
    ``lib.profile_dir`` is pointed at a private per-test directory since a
    ``.pls``/``.xsp`` source now derives a ``bgm.m3u`` there.

    Args:
        tmp_path: pytest's per-test temporary directory.
        name: Filename to create, extension included.
        monkeypatch: Used to point the addon profile at ``tmp_path``.
        content: Non-empty to produce one resolvable track; empty reproduces
            FR-010's "nothing playable" case for every format alike.

    Returns:
        The absolute path now configured as the BGM source.
    """
    path = tmp_path / name
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    track = content.strip()
    extension = path.suffix.lower()
    if extension == ".pls":
        if track:
            real_track = tmp_path / "pls-track.mp3"
            real_track.write_text("fake audio", encoding="utf-8")
            track = str(real_track)
        entry = "File1={0}\n".format(track) if track else ""
        path.write_text("[playlist]\n" + entry, encoding="utf-8")
    elif extension == ".xsp":
        path.write_text('<smartplaylist type="songs"/>', encoding="utf-8")
        if track:
            world.xsp_directories[str(path)] = [{"file": track, "filetype": "file"}]
    else:
        path.write_text(content, encoding="utf-8")
    store.settings["type"] = "Playlist"
    store.settings["playlist"] = str(path)
    return str(path)


def _configure_directory(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    files: Tuple[str, ...] = ("a.mp3", KOREAN_TRACK),
) -> str:
    """Configure a real directory source and a private profile for bgm.m3u.

    Args:
        tmp_path: pytest's per-test temporary directory.
        monkeypatch: Used to point the addon profile at ``tmp_path``.
        files: Relative paths to create under the music directory. A ``/``
            in a name creates the subdirectory, which is how the recursive
            half of FR-006 gets exercised.

    Returns:
        The absolute path of the music directory now configured.
    """
    music = tmp_path / KOREAN_DIRECTORY
    for name in files:
        entry = music / name
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text("fake audio", encoding="utf-8")
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    store.settings["type"] = "Directory"
    store.settings["directory"] = str(music)
    return str(music)


# -- slideshow driver --------------------------------------------------------


def _drive_slideshow(
    monkeypatch: pytest.MonkeyPatch, observe: Optional[Callable[[], Any]] = None
) -> Dict[str, Any]:
    """Make Kodi behave like a slideshow that runs once and then exits.

    The first ``waitForAbort`` models Kodi's own causality after
    ``PlayMedia``: the track actually starts and ``onAVStarted`` fires
    (D-005). It then waits out the fade-in and snapshots what things looked
    like mid-playback, because everything is torn down again by the time
    ``run()`` returns. The second wait closes the slideshow.

    Args:
        monkeypatch: Used to replace ``Monitor.waitForAbort``.
        observe: Called mid-playback; its return value is recorded.

    Returns:
        A dict carrying what ``observe`` returned and what was playing at
        that moment.
    """
    observed: Dict[str, Any] = {"observed": None, "playing_file": None}
    world.conditions["Slideshow.IsActive"] = True
    waits = {"count": 0}
    real_wait = xbmc.Monitor.waitForAbort

    def counting(self: Any, timeout: float) -> bool:
        waits["count"] += 1
        if waits["count"] == 1:
            if world.play_media_calls:
                world.start_audio(world.play_media_calls[-1]["path"])
                world.playlist_position = "1"
                world.fire_av_started()
            fader.join(JOIN_SECONDS)
            observed["playing_file"] = world.current_file
            observed["observed"] = observe() if observe is not None else None
            return bool(real_wait(self, timeout))
        world.conditions["Slideshow.IsActive"] = False
        return bool(real_wait(self, timeout))

    monkeypatch.setattr(xbmc.Monitor, "waitForAbort", counting)
    return observed


def _run_slideshow(
    monkeypatch: pytest.MonkeyPatch,
) -> Tuple[SlideshowSession, Dict[str, Any]]:
    """Run one whole session, start to teardown, and report what was seen."""
    session = SlideshowSession()
    observed = _drive_slideshow(monkeypatch, observe=lambda: session.state)
    session.run()
    return session, observed


def _record_stops(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    """Record what was playing each time anything called ``Player.stop``.

    FR-014's TakeOver policy is defined by that stop happening to someone
    else's playback; the fake would otherwise hide it, since the BGM that
    starts next overwrites ``world.current_file`` either way.

    Args:
        monkeypatch: Used to wrap the fake ``xbmc.Player.stop``.

    Returns:
        A list that fills with the file playing at each stop, in order.
    """
    stopped: List[str] = []
    real_stop = xbmc.Player.stop

    def recording(self: Any) -> None:
        if world.playing is not None:
            stopped.append(world.current_file)
        real_stop(self)

    monkeypatch.setattr(xbmc.Player, "stop", recording)
    return stopped


def _played_playlist() -> str:
    """The single playlist path this session handed to ``PlayMedia``."""
    assert len(world.play_media_calls) == 1, world.play_media_calls
    path: str = world.play_media_calls[0]["path"]
    return path


def _read_lines(path: str) -> List[str]:
    with open(path, encoding="utf-8") as handle:
        return handle.read().splitlines()


def _one_log(prefix: str) -> str:
    """The single logged line starting with ``prefix``, header stripped."""
    header = messages.LOG_HEADER
    entries: List[str] = [
        message[len(header) :]
        for message, _level in world.log_lines
        if message.startswith(header + prefix)
    ]
    assert len(entries) == 1, "expected one {0!r} line, got {1}".format(prefix, entries)
    return entries[0]


# -- scenario 1: a directory source is scanned recursively (FR-006, SC-005) --


def test_a_directory_source_is_scanned_into_the_playlist_kodi_is_handed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    music = _configure_directory(
        tmp_path,
        monkeypatch,
        files=("a.mp3", "sub/b.flac", "sub/deeper/c.ogg", KOREAN_TRACK),
    )

    _run_slideshow(monkeypatch)

    played = _played_playlist()
    assert played.endswith("bgm.m3u")
    assert _read_lines(played) == sorted(
        [
            str(pathlib.Path(music) / "a.mp3"),
            str(pathlib.Path(music) / "sub" / "b.flac"),
            str(pathlib.Path(music) / "sub" / "deeper" / "c.ogg"),
            str(pathlib.Path(music) / KOREAN_TRACK),
        ]
    )


def test_a_directory_source_leaves_unsupported_files_out_of_the_playlist(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_directory(
        tmp_path,
        monkeypatch,
        files=("keep.mp3", "cover.jpg", "notes.txt", "sub/readme.md", "sub/keep.m4a"),
    )

    _run_slideshow(monkeypatch)

    names = [pathlib.Path(line).name for line in _read_lines(_played_playlist())]
    assert sorted(names) == ["keep.m4a", "keep.mp3"]


def test_a_korean_named_track_round_trips_through_the_derived_playlist(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # D-009: the scan walks bytes and the playlist is written UTF-8, so the
    # name Kodi is handed must come back byte-for-byte identical.
    music = _configure_directory(tmp_path, monkeypatch, files=(KOREAN_TRACK,))

    _run_slideshow(monkeypatch)

    assert _read_lines(_played_playlist()) == [str(pathlib.Path(music) / KOREAN_TRACK)]


def test_a_directory_source_actually_plays(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_directory(tmp_path, monkeypatch)

    session, observed = _run_slideshow(monkeypatch)

    assert observed["observed"] is SessionState.PLAYING
    assert session.state is SessionState.TERMINATED


# -- scenario 2: any of the three playlist formats (FR-007) ------------------


@pytest.mark.parametrize("name", ["mix.m3u", "mix.M3U"])
def test_an_m3u_playlist_source_is_handed_to_kodi_exactly_as_configured(
    name: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The addon never parses .m3u; it hands the path over untouched and lets
    # PlayMedia read it.
    path = _configure_playlist_file(tmp_path, name, monkeypatch)

    _run_slideshow(monkeypatch)

    assert world.play_media_calls == [{"path": path, "playoffset": None}]


@pytest.mark.parametrize("name", ["mix.pls", "smart.xsp", "mix.PLS", "smart.XSP"])
def test_a_pls_or_xsp_source_is_resolved_before_playmedia_ever_sees_it(
    name: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Kodi's own playoffset resume never advances past track 1 for these two
    # formats (real-device Tier 2 finding), so the addon resolves them itself
    # into a derived bgm.m3u and hands PlayMedia that instead of the raw path.
    _configure_playlist_file(tmp_path, name, monkeypatch)

    _run_slideshow(monkeypatch)

    assert len(world.play_media_calls) == 1
    played = world.play_media_calls[0]["path"]
    assert played.endswith("bgm.m3u")
    if name.lower().endswith(".pls"):
        expected_track = str(tmp_path / "pls-track.mp3")
    else:
        expected_track = "/music/a.mp3"
    assert _read_lines(played) == [expected_track]


@pytest.mark.parametrize("name", ["mix.m3u", "mix.pls", "smart.xsp"])
def test_a_playlist_source_of_any_format_reaches_playing(
    name: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist_file(tmp_path, name, monkeypatch)

    _, observed = _run_slideshow(monkeypatch)

    assert observed["observed"] is SessionState.PLAYING


def test_a_korean_named_playlist_file_is_handed_over_intact(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _configure_playlist_file(tmp_path, "재즈-모음.m3u", monkeypatch)

    _run_slideshow(monkeypatch)

    assert _played_playlist() == path


@pytest.mark.parametrize("name", ["mix.m3u", "mix.pls", "smart.xsp"])
def test_an_empty_playlist_of_any_format_disables_bgm_rather_than_playing_it(
    name: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FR-010 holds for every format, not just the one US1 happened to use.
    _configure_playlist_file(tmp_path, name, monkeypatch, content="")

    _, observed = _run_slideshow(monkeypatch)

    assert world.play_media_calls == []
    assert observed["observed"] is SessionState.DISABLED


# -- scenario 3: shuffle is honored where it can be (FR-008) -----------------


def test_shuffle_on_a_directory_source_primes_random_playback(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_directory(tmp_path, monkeypatch)
    store.settings["random"] = "true"

    _run_slideshow(monkeypatch)

    assert RANDOM_ON in world.builtins
    assert RANDOM_OFF not in world.builtins


@pytest.mark.parametrize("name", ["mix.m3u", "mix.M3U"])
def test_shuffle_on_an_m3u_playlist_primes_random_playback(
    name: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist_file(tmp_path, name, monkeypatch)
    store.settings["random"] = "true"

    _run_slideshow(monkeypatch)

    assert RANDOM_ON in world.builtins
    assert RANDOM_OFF not in world.builtins


def test_shuffle_off_primes_sequential_playback_for_a_directory_source(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_directory(tmp_path, monkeypatch)
    store.settings["random"] = "false"

    _run_slideshow(monkeypatch)

    assert RANDOM_OFF in world.builtins
    assert RANDOM_ON not in world.builtins


# -- scenario 4: shuffle is ignored for .pls and .xsp (FR-008) ---------------


@pytest.mark.parametrize(
    "name", ["mix.pls", "smart.xsp", "mix.PLS", "smart.XSP", "mix.Pls"]
)
def test_shuffle_is_ignored_for_a_pls_or_xsp_playlist(
    name: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # US3 scenario 4: the setting is on, and the playlist's own order still
    # wins. Case-insensitively -- D-011's cosmetic grey-out may miss a .PLS,
    # but the behavior here must not.
    _configure_playlist_file(tmp_path, name, monkeypatch)
    store.settings["random"] = "true"

    _run_slideshow(monkeypatch)

    assert RANDOM_OFF in world.builtins
    assert RANDOM_ON not in world.builtins


@pytest.mark.parametrize("name", ["mix.pls", "smart.xsp"])
def test_shuffle_being_ignored_is_recorded_in_the_session_start_log(
    name: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FR-009: the log has to say what was actually done, not what was asked
    # for, or it would be misleading about the one case FR-008 carves out.
    path = _configure_playlist_file(tmp_path, name, monkeypatch)
    store.settings["random"] = "true"

    _run_slideshow(monkeypatch)

    assert _one_log("session start:") == (
        "session start: version=0.1.0 source=PLAYLIST:{0} shuffle=False".format(path)
    )


def test_a_directory_named_like_a_pls_playlist_still_shuffles(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # What actually plays is the derived bgm.m3u, so the directory's own name
    # must not decide anything.
    _configure_directory(tmp_path, monkeypatch)
    store.settings["random"] = "true"
    renamed = tmp_path / "my.xsp"
    (tmp_path / KOREAN_DIRECTORY).rename(renamed)
    store.settings["directory"] = str(renamed)

    _run_slideshow(monkeypatch)

    assert RANDOM_ON in world.builtins
    assert RANDOM_OFF not in world.builtins


# -- scenario 5: audio Kodi is already playing (FR-014) ---------------------


def test_take_over_stops_the_existing_playback_and_starts_bgm(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _configure_playlist_file(tmp_path, "mix.m3u", monkeypatch)
    store.settings["on_existing_playback"] = "TakeOver"
    stopped = _record_stops(monkeypatch)
    world.start_audio(OTHER_MUSIC)

    _, observed = _run_slideshow(monkeypatch)

    assert stopped[0] == OTHER_MUSIC
    assert world.play_media_calls == [{"path": path, "playoffset": None}]
    assert observed["playing_file"] == path
    assert observed["observed"] is SessionState.PLAYING


def test_take_over_is_what_an_unset_setting_does(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FR-014: "this setting MUST default to stopping existing playback".
    path = _configure_playlist_file(tmp_path, "mix.m3u", monkeypatch)
    store.settings.pop("on_existing_playback", None)
    stopped = _record_stops(monkeypatch)
    world.start_audio(OTHER_MUSIC)

    _run_slideshow(monkeypatch)

    assert stopped[0] == OTHER_MUSIC
    assert world.play_media_calls == [{"path": path, "playoffset": None}]


def test_yield_leaves_the_existing_playback_completely_untouched(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist_file(tmp_path, "mix.m3u", monkeypatch)
    store.settings["on_existing_playback"] = "Yield"
    stopped = _record_stops(monkeypatch)
    world.start_audio(OTHER_MUSIC)

    session, observed = _run_slideshow(monkeypatch)

    assert world.play_media_calls == []
    assert stopped == []
    assert observed["observed"] is SessionState.DISABLED
    assert session.state is SessionState.TERMINATED
    # Still playing the same thing it was before the slideshow ever started.
    assert world.playing == "audio"
    assert world.current_file == OTHER_MUSIC


def test_yield_leaves_the_volume_alone_as_well(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "Untouched" includes not fading someone else's music (D-003, FR-016).
    _configure_playlist_file(tmp_path, "mix.m3u", monkeypatch)
    store.settings["on_existing_playback"] = "Yield"
    world.start_audio(OTHER_MUSIC)
    world.volume = 37

    _run_slideshow(monkeypatch)

    assert world.volume_calls == []
    assert world.volume == 37


def test_yield_with_nothing_already_playing_still_starts_bgm(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _configure_playlist_file(tmp_path, "mix.m3u", monkeypatch)
    store.settings["on_existing_playback"] = "Yield"

    _, observed = _run_slideshow(monkeypatch)

    assert world.play_media_calls == [{"path": path, "playoffset": None}]
    assert observed["observed"] is SessionState.PLAYING


def test_take_over_with_nothing_already_playing_stops_nothing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _configure_playlist_file(tmp_path, "mix.m3u", monkeypatch)
    store.settings["on_existing_playback"] = "TakeOver"
    stopped = _record_stops(monkeypatch)

    _run_slideshow(monkeypatch)

    assert world.play_media_calls == [{"path": path, "playoffset": None}]
    # Only the session's own teardown stop, on its own BGM -- nobody else's.
    assert stopped == [path]
