"""User Story 1 -- background music plays for the duration of a slideshow.

Covers spec.md US1 acceptance scenarios 1-3 and quickstart.md's Tier 1
story-level rows for US1: FR-001 (BGM starts), FR-004 (everything stops and is
joined at slideshow exit), FR-009 (the lifecycle log lines of
contracts/logging.md), FR-010/FR-012 (a missing or empty source disables BGM
with a non-blocking notification and never a dialog), FR-013 (1-second fades)
and FR-016 (the user's volume is never left altered).

Everything below drives the real ``session``/``player``/``fader``/``config``
modules against the in-repo Kodi fakes (research.md D-008) -- the only thing
mocked out is FR-013's 1-second fade duration, shrunk to keep the suite fast;
the ramp itself is the real one, on a real daemon thread.
"""

import pathlib
from typing import Any, Callable, Dict, Iterator, List, NamedTuple, Optional, Tuple

import pytest
import xbmc
import xbmcaddon
import xbmcgui

import addon
from resources import lib
from resources.lib import config, fader, messages
from resources.lib.fader import Direction
from resources.lib.playlist import BgmSource
from resources.lib.session import SessionState, SlideshowSession

world = xbmc.world
store = xbmcaddon.store
dialog_calls = xbmcgui.calls

#: Ramp time actually run in tests; production asks for FR-013's 1000 ms.
FAST_MS = 40
FADE_DURATION_MS = 1000
JOIN_SECONDS = 2.0

ADDON_NAME = "Slideshow-BGM"
BGM_UNAVAILABLE_TEXT = (
    "Background music is unavailable for this slideshow; continuing without it."
)
XSP_NOT_MUSIC_TEXT = (
    "The selected smart playlist is not a Music (Songs) playlist; background "
    "music is unavailable for this slideshow."
)
KOREAN_TRACK = "강허달림-기다림설레임.mp3"

SourceFactory = Callable[[pathlib.Path, pytest.MonkeyPatch], None]


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


@pytest.fixture()
def localized_messages() -> None:
    """Give strings.po id #32004 its real English text (FR-012)."""
    store.localized_strings[32004] = BGM_UNAVAILABLE_TEXT


@pytest.fixture()
def localized_xsp_message() -> None:
    """Give strings.po id #32005 its real English text (FR-012)."""
    store.localized_strings[32005] = XSP_NOT_MUSIC_TEXT


# -- source helpers ----------------------------------------------------------


def _configure_playlist(tmp_path: pathlib.Path, content: str = "/music/a.mp3\n") -> str:
    """Configure a real, non-empty ``.m3u`` playlist source."""
    path = tmp_path / "my.m3u"
    path.write_text(content, encoding="utf-8")
    store.settings["type"] = "Playlist"
    store.settings["playlist"] = str(path)
    return str(path)


def _configure_directory(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    names: Tuple[str, ...] = ("a.mp3", "b.flac"),
) -> str:
    """Configure a real directory source and a private profile for bgm.m3u."""
    music = tmp_path / "music"
    music.mkdir(parents=True, exist_ok=True)
    for name in names:
        (music / name).write_text("fake audio", encoding="utf-8")
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    store.settings["type"] = "Directory"
    store.settings["directory"] = str(music)
    return str(music)


# -- slideshow driver --------------------------------------------------------


class Observation(NamedTuple):
    """What a driven slideshow looked like while it was still running."""

    session: SlideshowSession
    state_while_playing: Optional[SessionState]
    volume_calls_while_playing: List[Tuple[int, bool]]


def _drive_slideshow(
    monkeypatch: pytest.MonkeyPatch,
    abort: bool = False,
    observe: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    """Make Kodi behave like a slideshow that runs once and then exits.

    The first ``waitForAbort`` models Kodi's own causality after ``PlayMedia``:
    the track actually starts and ``onAVStarted`` fires (D-005). It then waits
    out the fade-in and snapshots what the session looked like mid-playback,
    because everything is torn down again by the time ``run()`` returns. The
    second wait ends the slideshow -- either by closing it or, when ``abort``
    is set, by Kodi asking the addon to abort.
    """
    observed: Dict[str, Any] = {"state": None, "volume_calls": []}
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
            observed["volume_calls"] = list(world.volume_calls)
            observed["state"] = observe() if observe is not None else None
            return bool(real_wait(self, timeout))
        if abort:
            world.abort_requested = True
        else:
            world.conditions["Slideshow.IsActive"] = False
        return bool(real_wait(self, timeout))

    monkeypatch.setattr(xbmc.Monitor, "waitForAbort", counting)
    return observed


def _run_slideshow(monkeypatch: pytest.MonkeyPatch, abort: bool = False) -> Observation:
    """Run one whole session, start to teardown, and report what was seen."""
    session = SlideshowSession()
    observed = _drive_slideshow(monkeypatch, abort=abort, observe=lambda: session.state)
    session.run()
    return Observation(
        session=session,
        state_while_playing=observed["state"],
        volume_calls_while_playing=observed["volume_calls"],
    )


# -- log helpers -------------------------------------------------------------


def _log_entries(prefix: str) -> List[Tuple[str, int]]:
    """Every logged line starting with ``prefix``, header stripped."""
    header = messages.LOG_HEADER
    return [
        (message[len(header) :], level)
        for message, level in world.log_lines
        if message.startswith(header + prefix)
    ]


def _one_log(prefix: str) -> Tuple[str, int]:
    """The single line starting with ``prefix`` -- logging.md says exactly one."""
    entries = _log_entries(prefix)
    assert len(entries) == 1, "expected exactly one {0!r} line, got {1}".format(
        prefix, entries
    )
    return entries[0]


def _volumes(calls: List[Tuple[int, bool]]) -> List[int]:
    return [percent for percent, _ in calls]


def _builtin_indices(prefix: str) -> List[int]:
    """Where every builtin call starting with ``prefix`` landed, in order."""
    return [
        index for index, call in enumerate(world.builtins) if call.startswith(prefix)
    ]


# -- scenario 1: a valid source starts background music (FR-001, SC-001) -----


def test_a_valid_playlist_source_is_handed_to_playmedia(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    playlist_path = _configure_playlist(tmp_path)

    _run_slideshow(monkeypatch)

    assert world.play_media_calls == [{"path": playlist_path, "playoffset": None}]


def test_a_valid_directory_source_is_resolved_before_playmedia(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_directory(tmp_path, monkeypatch)

    _run_slideshow(monkeypatch)

    assert len(world.play_media_calls) == 1
    assert world.play_media_calls[0]["path"].endswith("bgm.m3u")


def test_a_korean_named_track_round_trips_into_the_playlist_handed_to_kodi(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_directory(tmp_path, monkeypatch, names=(KOREAN_TRACK,))

    _run_slideshow(monkeypatch)

    derived = world.play_media_calls[0]["path"]
    with open(derived, encoding="utf-8") as handle:
        written = handle.read().splitlines()
    assert [pathlib.Path(line).name for line in written] == [KOREAN_TRACK]


def test_the_session_is_playing_while_the_slideshow_runs(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)

    observed = _run_slideshow(monkeypatch)

    assert observed.state_while_playing is SessionState.PLAYING


def test_playback_starts_before_shuffle_and_repeat_are_primed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # research.md D-006: PlayerControl only takes effect while a player is
    # active, so playback has to be established first.
    _configure_playlist(tmp_path)

    _run_slideshow(monkeypatch)

    started = _builtin_indices("PlayMedia(")
    primed = _builtin_indices("PlayerControl(")
    assert started and primed
    assert max(started) < min(primed)


def test_the_fade_in_is_held_until_shuffle_and_repeat_are_primed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # D-006: the user must never hear an unshuffled first moment.
    _configure_playlist(tmp_path)

    _run_slideshow(monkeypatch)

    primed = _builtin_indices("PlayerControl(")
    faded = _builtin_indices("SetVolume(")
    assert primed and faded
    assert max(primed) < min(faded)


def test_the_playlist_loops_so_bgm_outlasts_the_slideshow(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Assumption 5: BGM loops rather than ending before the slideshow does.
    _configure_playlist(tmp_path)

    _run_slideshow(monkeypatch)

    assert "PlayerControl(RepeatAll)" in world.builtins


def test_shuffle_on_primes_random_playback(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)
    store.settings["random"] = "true"

    _run_slideshow(monkeypatch)

    assert "PlayerControl(RandomOn)" in world.builtins
    assert "PlayerControl(RandomOff)" not in world.builtins


def test_shuffle_off_primes_sequential_playback(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)
    store.settings["random"] = "false"

    _run_slideshow(monkeypatch)

    assert "PlayerControl(RandomOff)" in world.builtins
    assert "PlayerControl(RandomOn)" not in world.builtins


def test_the_volume_ramps_from_silence_up_to_the_users_level(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)
    world.volume = 55

    observed = _run_slideshow(monkeypatch)

    ramp = _volumes(observed.volume_calls_while_playing)
    assert ramp[0] == 0
    assert ramp[-1] == 55
    assert len(ramp) > 2
    assert ramp == sorted(ramp)


def test_the_fade_in_asks_for_the_one_second_ramp_fr013(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    fade_requests: List[Tuple[Direction, int, int]],
) -> None:
    _configure_playlist(tmp_path)
    world.volume = 70

    _run_slideshow(monkeypatch)

    assert fade_requests[0] == (Direction.IN, 70, FADE_DURATION_MS)


def test_starting_bgm_shows_no_dialog(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)

    _run_slideshow(monkeypatch)

    assert dialog_calls.ok_calls == []
    assert dialog_calls.yesno_calls == []
    assert dialog_calls.notifications == []


# -- scenario 2: the slideshow ends (FR-004, FR-013, FR-016, SC-003) --------


def test_the_slideshow_closing_fades_the_music_out(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    fade_requests: List[Tuple[Direction, int, int]],
) -> None:
    _configure_playlist(tmp_path)
    world.volume = 60

    _run_slideshow(monkeypatch)

    assert [direction for direction, _, _ in fade_requests] == [
        Direction.IN,
        Direction.OUT,
    ]
    assert fade_requests[-1] == (Direction.OUT, 60, FADE_DURATION_MS)


def test_the_slideshow_closing_stops_playback(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)

    _run_slideshow(monkeypatch)

    assert world.playing is None


def test_teardown_leaves_no_fade_thread_running(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)

    _run_slideshow(monkeypatch)

    # Nothing to wait for: a still-running ramp would fail a zero-length join.
    assert fader.join(0.0) is True


def test_teardown_restores_the_users_volume(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)
    world.volume = 45

    _run_slideshow(monkeypatch)

    assert world.volume_calls[-1] == (45, False)
    assert world.volume == 45


def test_a_volume_change_made_during_the_slideshow_survives_it(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FR-016: teardown restores the level last observed while BGM was
    # audible, not the one captured at session start.
    _configure_playlist(tmp_path)
    world.volume = 30

    def turn_it_up() -> None:
        world.volume = 90

    _drive_slideshow(monkeypatch, observe=turn_it_up)
    SlideshowSession().run()

    assert world.volume == 90
    assert world.volume_calls[-1] == (90, False)


def test_a_failure_mid_fade_still_stops_playback_and_restores_the_volume(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # quickstart.md names this exit path by name: the volume invariant (D-003)
    # has to hold for a clean end, an abort, *and* an exception mid-fade.
    _configure_playlist(tmp_path)
    world.volume = 35
    faded = fader.fade

    def explode_on_the_way_out(
        direction: Direction, baseline: int, duration_ms: int = FADE_DURATION_MS
    ) -> None:
        if direction is Direction.OUT:
            raise RuntimeError("Kodi is shutting down")
        faded(direction, baseline, duration_ms)

    _drive_slideshow(monkeypatch)
    monkeypatch.setattr(fader, "fade", explode_on_the_way_out)
    session = SlideshowSession()

    with pytest.raises(RuntimeError):
        session.run()

    assert session.state is SessionState.TERMINATED
    assert world.playing is None
    assert world.volume == 35
    assert world.volume_calls[-1] == (35, False)
    assert _one_log("session end:")[0].endswith("volume restored to 35")


def test_no_volume_call_ever_asks_kodi_to_show_the_volume_bar(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # R-2 regression guard, at session level this time (D-013).
    _configure_playlist(tmp_path)
    world.volume = 65

    _run_slideshow(monkeypatch)

    assert len(world.volume_calls) > 4
    assert [shown for _, shown in world.volume_calls] == [False] * len(
        world.volume_calls
    )


def test_the_session_ends_terminated(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)

    observed = _run_slideshow(monkeypatch)

    assert observed.session.state is SessionState.TERMINATED


def test_an_abort_request_also_tears_the_session_down(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    fade_requests: List[Tuple[Direction, int, int]],
) -> None:
    _configure_playlist(tmp_path)
    world.volume = 50

    observed = _run_slideshow(monkeypatch, abort=True)

    assert observed.session.state is SessionState.TERMINATED
    assert Direction.OUT in [direction for direction, _, _ in fade_requests]
    assert world.playing is None
    assert world.volume == 50


# -- FR-009 lifecycle log lines (contracts/logging.md) -----------------------


def test_session_start_names_the_source_and_shuffle_setting(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    playlist_path = _configure_playlist(tmp_path)
    store.settings["random"] = "true"

    _run_slideshow(monkeypatch)

    assert _one_log("session start:") == (
        "session start: source=PLAYLIST:{0} shuffle=True".format(playlist_path),
        xbmc.LOGINFO,
    )


def test_bgm_start_is_logged_once(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)

    _run_slideshow(monkeypatch)

    message, level = _one_log("BGM start:")
    assert message.startswith("BGM start: track=")
    assert level == xbmc.LOGINFO


def test_session_end_reports_the_restored_volume(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # logging.md: this line is the evidence for the D-003 volume invariant.
    _configure_playlist(tmp_path)
    world.volume = 45

    _run_slideshow(monkeypatch)

    assert _one_log("session end:") == (
        "session end: reason=slideshow_closed volume restored to 45",
        xbmc.LOGINFO,
    )


def test_session_end_names_an_abort_as_the_reason(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)
    world.volume = 80

    _run_slideshow(monkeypatch, abort=True)

    assert _one_log("session end:") == (
        "session end: reason=abort_requested volume restored to 80",
        xbmc.LOGINFO,
    )


def test_session_end_is_logged_even_when_bgm_was_never_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world.volume = 33

    _run_slideshow(monkeypatch)

    assert _one_log("session end:") == (
        "session end: reason=slideshow_closed volume restored to 33",
        xbmc.LOGINFO,
    )


# -- scenario 3: nothing configured (FR-010, US1 scenario 3) ----------------


def test_no_source_configured_plays_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    assert store.settings["playlist"] == "Not Selected"

    observed = _run_slideshow(monkeypatch)

    assert world.play_media_calls == []
    assert observed.state_while_playing is SessionState.DISABLED


def test_no_source_configured_shows_the_user_nothing_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # US1 scenario 3: "no error shown to the user" -- not even a toast; FR-012's
    # notification is for a source that *was* configured and has gone bad.
    _run_slideshow(monkeypatch)

    assert dialog_calls.ok_calls == []
    assert dialog_calls.yesno_calls == []
    assert dialog_calls.notifications == []


def test_no_source_configured_leaves_the_volume_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world.volume = 42

    _run_slideshow(monkeypatch)

    assert world.volume_calls == []
    assert world.volume == 42


def test_no_source_configured_is_logged_as_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_slideshow(monkeypatch)

    assert _one_log("BGM disabled:") == ("BGM disabled: not_selected", xbmc.LOGINFO)


def test_no_source_configured_still_runs_the_session_to_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = _run_slideshow(monkeypatch)

    assert observed.session.state is SessionState.TERMINATED


# -- FR-012: a configured source that has gone bad --------------------------


def _missing_playlist(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store.settings["type"] = "Playlist"
    store.settings["playlist"] = str(tmp_path / "deleted.m3u")


def _empty_playlist(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_playlist(tmp_path, content="")


def _missing_directory(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    store.settings["type"] = "Directory"
    store.settings["directory"] = str(tmp_path / "unplugged-drive")


def _silent_directory(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_directory(tmp_path, monkeypatch, names=("cover.jpg", "notes.txt"))


BAD_SOURCES: List[Tuple[SourceFactory, str]] = [
    (_missing_playlist, "missing"),
    (_empty_playlist, "empty"),
    (_missing_directory, "missing"),
    (_silent_directory, "empty"),
]


@pytest.mark.parametrize(
    "configure,reason", BAD_SOURCES, ids=[reason for _, reason in BAD_SOURCES]
)
def test_a_bad_source_of_either_kind_disables_bgm_without_playing_anything(
    configure: SourceFactory,
    reason: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(tmp_path, monkeypatch)

    observed = _run_slideshow(monkeypatch)

    assert world.play_media_calls == []
    assert observed.state_while_playing is SessionState.DISABLED
    assert observed.session.state is SessionState.TERMINATED


@pytest.mark.parametrize(
    "configure,reason", BAD_SOURCES, ids=[reason for _, reason in BAD_SOURCES]
)
def test_a_bad_source_of_either_kind_is_logged_with_its_reason(
    configure: SourceFactory,
    reason: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(tmp_path, monkeypatch)

    _run_slideshow(monkeypatch)

    assert _one_log("BGM disabled:") == (
        "BGM disabled: {0}".format(reason),
        xbmc.LOGINFO,
    )


@pytest.mark.parametrize(
    "configure,reason", BAD_SOURCES, ids=[reason for _, reason in BAD_SOURCES]
)
def test_a_bad_source_of_either_kind_notifies_without_blocking(
    configure: SourceFactory,
    reason: str,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    localized_messages: None,
) -> None:
    configure(tmp_path, monkeypatch)

    _run_slideshow(monkeypatch)

    assert dialog_calls.notifications == [
        (ADDON_NAME, BGM_UNAVAILABLE_TEXT, xbmcgui.NOTIFICATION_INFO)
    ]
    assert dialog_calls.ok_calls == []
    assert dialog_calls.yesno_calls == []


def test_a_source_that_disappears_mid_start_disables_bgm_instead_of_raising(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    localized_messages: None,
) -> None:
    # Edge Case 2 at its narrowest: a network share or USB drive that goes
    # away between validation and playback. FR-010 -- the slideshow must not
    # fail, whichever side of the check the source vanishes on.
    playlist_path = _configure_playlist(tmp_path)
    real_validate = config.validate

    def validate_then_unplug(source: BgmSource) -> config.ValidationResult:
        result = real_validate(source)
        pathlib.Path(playlist_path).unlink()
        return result

    monkeypatch.setattr(config, "validate", validate_then_unplug)

    observed = _run_slideshow(monkeypatch)

    assert world.play_media_calls == []
    assert observed.state_while_playing is SessionState.DISABLED
    assert observed.session.state is SessionState.TERMINATED
    assert _one_log("BGM disabled:") == ("BGM disabled: empty", xbmc.LOGINFO)
    assert dialog_calls.notifications == [
        (ADDON_NAME, BGM_UNAVAILABLE_TEXT, xbmcgui.NOTIFICATION_INFO)
    ]
    assert dialog_calls.ok_calls == []


def _non_music_smartplaylist(tmp_path: pathlib.Path) -> str:
    """Configure a real ``.xsp`` whose smart-playlist type is not music."""
    path = tmp_path / "smart.xsp"
    path.write_text('<smartplaylist type="movies"/>', encoding="utf-8")
    store.settings["type"] = "Playlist"
    store.settings["playlist"] = str(path)
    return str(path)


def test_a_non_music_smartplaylist_disables_bgm_with_its_own_error_notification(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    localized_xsp_message: None,
) -> None:
    # A movies/musicvideos/mixed .xsp can resolve to real, playable *video*
    # files, so it must be rejected by name rather than silently played as
    # background music -- and said with an error icon, not the generic
    # informational "unavailable" toast the other bad sources get.
    _non_music_smartplaylist(tmp_path)

    observed = _run_slideshow(monkeypatch)

    assert world.play_media_calls == []
    assert observed.state_while_playing is SessionState.DISABLED
    assert _one_log("BGM disabled:") == (
        "BGM disabled: not_music_playlist",
        xbmc.LOGINFO,
    )
    assert dialog_calls.notifications == [
        (ADDON_NAME, XSP_NOT_MUSIC_TEXT, xbmcgui.NOTIFICATION_ERROR)
    ]
    assert dialog_calls.ok_calls == []
    assert dialog_calls.yesno_calls == []


def test_a_bad_source_leaves_the_users_volume_untouched(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _missing_playlist(tmp_path, monkeypatch)
    world.volume = 25

    _run_slideshow(monkeypatch)

    assert world.volume_calls == []
    assert world.volume == 25


# -- FR-014: what to do about playback already in progress ------------------


def test_take_over_stops_existing_playback_before_starting_bgm(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    playlist_path = _configure_playlist(tmp_path)
    store.settings["on_existing_playback"] = "TakeOver"
    world.start_audio("/music/someone-elses-album.mp3")

    _run_slideshow(monkeypatch)

    assert world.play_media_calls == [{"path": playlist_path, "playoffset": None}]


def test_yield_leaves_existing_playback_alone_and_skips_bgm(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)
    store.settings["on_existing_playback"] = "Yield"
    world.start_audio("/music/someone-elses-album.mp3")

    observed = _run_slideshow(monkeypatch)

    assert world.play_media_calls == []
    assert world.playing == "audio"
    assert world.current_file == "/music/someone-elses-album.mp3"
    assert observed.state_while_playing is SessionState.DISABLED


def test_yield_with_nothing_playing_still_starts_bgm(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    playlist_path = _configure_playlist(tmp_path)
    store.settings["on_existing_playback"] = "Yield"

    _run_slideshow(monkeypatch)

    assert world.play_media_calls == [{"path": playlist_path, "playoffset": None}]


def test_yield_logs_why_bgm_was_disabled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)
    store.settings["on_existing_playback"] = "Yield"
    world.start_audio("/music/someone-elses-album.mp3")

    _run_slideshow(monkeypatch)

    message, level = _one_log("BGM disabled:")
    assert "existing playback" in message
    assert level == xbmc.LOGINFO


# -- the Script Mode entry point (T026) -------------------------------------


def test_the_addon_entry_point_runs_one_whole_session(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    playlist_path = _configure_playlist(tmp_path)
    world.volume = 40
    _drive_slideshow(monkeypatch)

    addon.main()

    assert world.play_media_calls == [{"path": playlist_path, "playoffset": None}]
    assert world.volume == 40
    assert _one_log("session end:")[0].endswith("volume restored to 40")
