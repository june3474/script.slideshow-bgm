"""User Story 2 -- background music pauses for video clips and resumes after.

Covers spec.md US2 acceptance scenarios 1-3, Edge Case 4 (back-to-back clips)
and Edge Case 3's "leave whatever is on screen alone" half: FR-002 (a clip
suspends BGM), FR-003 (the clip ending resumes at the following track),
FR-004's precedence over FR-003 (a clip ending as the slideshow exits must not
resume), FR-013 (the clip's own audio fades in from silence), FR-016 (a volume
change the user makes mid-session survives a whole suspend/resume cycle) and
the FR-009 log lines of contracts/logging.md.

Everything below drives the real ``session``/``player``/``fader``/``config``
modules against the in-repo Kodi fakes (research.md D-008); the fake's
``start_video_clip`` reproduces the probe-confirmed D-001 causality exactly.
The only thing mocked out is FR-013's 1-second fade duration, shrunk to keep
the suite fast -- the ramp itself is the real one, on a real daemon thread.
"""

import pathlib
from typing import Any, Callable, Iterator, List, Optional, Tuple

import pytest
import xbmc
import xbmcaddon

from resources.lib import fader, messages
from resources.lib.fader import Direction
from resources.lib.session import SessionState, SlideshowSession

world = xbmc.world
store = xbmcaddon.store

#: Ramp time actually run in tests; production asks for FR-013's 1000 ms.
FAST_MS = 40
FADE_DURATION_MS = 1000
JOIN_SECONDS = 2.0

#: Track Kodi reports as playing when the first clip interrupts BGM. D-005:
#: ``Playlist.Position(music)`` is 1-indexed, so the resume target is 4.
TRACK = 3
RESUME_OFFSET = TRACK + 1

CLIP = "/photos/holiday.mp4"
SECOND_CLIP = "/photos/beach.mp4"

Step = Callable[[], None]


# -- fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def fade_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[List[Tuple[Direction, int, int]]]:
    """Record what production asked ``fader.fade`` for, ramp it fast anyway."""
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


# -- source helper -----------------------------------------------------------


def _configure_playlist(tmp_path: pathlib.Path, tracks: int = 5) -> str:
    """Configure a real, non-empty ``.m3u`` playlist source."""
    path = tmp_path / "my.m3u"
    path.write_text(
        "".join("/music/{0}.mp3\n".format(number) for number in range(tracks)),
        encoding="utf-8",
    )
    store.settings["type"] = "Playlist"
    store.settings["playlist"] = str(path)
    return str(path)


# -- slideshow driver --------------------------------------------------------


def _bgm_actually_starts(track: Optional[int]) -> None:
    """Model Kodi's own causality after ``PlayMedia``: the track starts.

    ``onAVStarted`` is what tells the player which track is playing (D-005),
    and it is the only way the resume point is ever recorded. ``track=None``
    models the stream being up but that callback not having landed yet --
    ``PlayMedia`` is asynchronous, so a clip can interrupt before any index
    was ever read.
    """
    if not world.play_media_calls:
        return
    world.start_audio(world.play_media_calls[-1]["path"])
    if track is not None:
        world.playlist_position = str(track)
        world.fire_av_started()


def _drive(
    monkeypatch: pytest.MonkeyPatch,
    steps: List[Step],
    track: Optional[int] = TRACK,
    abort: bool = False,
) -> None:
    """Run one scripted step per ``Monitor`` wait, then end the slideshow.

    The first wait starts background music for real; each later wait runs the
    next scripted step and waits out its fade, so volume assertions never race
    a ramp. Once the script is exhausted the slideshow closes (or Kodi asks the
    addon to abort), which is what ends ``SlideshowSession.run``.
    """
    world.conditions["Slideshow.IsActive"] = True
    script = list(steps)
    waits = {"count": 0}
    real_wait = xbmc.Monitor.waitForAbort

    def scripted(self: Any, timeout: float) -> bool:
        index = waits["count"]
        waits["count"] += 1
        if index == 0:
            _bgm_actually_starts(track)
        elif index - 1 < len(script):
            script[index - 1]()
        elif abort:
            world.abort_requested = True
        else:
            world.conditions["Slideshow.IsActive"] = False
        fader.join(JOIN_SECONDS)
        return bool(real_wait(self, timeout))

    monkeypatch.setattr(xbmc.Monitor, "waitForAbort", scripted)


def _noting(step: Step, session: SlideshowSession, seen: List[SessionState]) -> Step:
    """Wrap ``step`` so the state it leaves the session in is recorded.

    Everything is torn down again by the time ``run()`` returns, so a
    transition can only be observed from inside the slideshow.
    """

    def stepped() -> None:
        step()
        seen.append(session.state)

    return stepped


def _run(
    monkeypatch: pytest.MonkeyPatch,
    steps: List[Step],
    track: Optional[int] = TRACK,
    abort: bool = False,
) -> SlideshowSession:
    """Run one whole session with ``steps`` happening while it plays."""
    session = SlideshowSession()
    _drive(monkeypatch, steps, track=track, abort=abort)
    session.run()
    return session


# -- slideshow events --------------------------------------------------------


def _clip_starts(path: str = CLIP) -> None:
    """A slideshow video clip claims the player (D-001).

    ``Slideshow.IsVideo`` is already true by the time the callback fires: the
    slide has switched, which is what the probe measured the callback latency
    *from*.
    """
    world.conditions["Slideshow.IsVideo"] = True
    world.start_video_clip(path)


def _clip_ends_on_an_image(ended: bool = False) -> None:
    """The clip finishes and the slideshow advances to an image (FR-003)."""
    world.conditions["Slideshow.IsVideo"] = False
    world.end_video_clip()
    if ended:
        world.fire_ended()
    else:
        world.fire_stopped()


def _clip_ends_as_the_slideshow_closes() -> None:
    """The slideshow window goes away at the very instant a clip ends."""
    world.conditions["Slideshow.IsActive"] = False
    _clip_ends_on_an_image()


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


def _volumes() -> List[int]:
    return [percent for percent, _ in world.volume_calls]


def _resume_calls() -> List[Optional[int]]:
    """The ``playoffset`` of every ``PlayMedia`` after the session's first."""
    return [call["playoffset"] for call in world.play_media_calls[1:]]


# -- scenario 1: a clip starting suspends BGM (FR-002, FR-013, SC-002) -------


def test_a_clip_starting_suspends_the_session(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)
    session = SlideshowSession()
    seen: List[SessionState] = []

    _drive(monkeypatch, [_noting(_clip_starts, session, seen)])
    session.run()

    assert seen == [SessionState.SUSPENDED]


def test_a_clip_starting_drops_the_volume_to_silence_at_once(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # R-6: the snap to 0 has to land inline on the callback thread, racing the
    # clip's audio becoming audible -- not after a ramp thread has started.
    _configure_playlist(tmp_path)
    world.volume = 60
    snapped: List[int] = []

    def clip_starts_and_we_look_immediately() -> None:
        _clip_starts()
        snapped.append(world.volume)

    _run(monkeypatch, [clip_starts_and_we_look_immediately])

    assert snapped == [0]


def test_the_clips_own_audio_fades_in_over_a_second(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    fade_requests: List[Tuple[Direction, int, int]],
) -> None:
    # FR-013/D-003: there is no BGM left to fade out (D-001), so the ramp at a
    # clip's start shapes the clip's incoming audio instead.
    _configure_playlist(tmp_path)
    world.volume = 60

    _run(monkeypatch, [_clip_starts])

    assert fade_requests[1] == (Direction.IN, 60, FADE_DURATION_MS)


def test_a_clip_starting_freezes_the_track_that_was_playing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # D-001 tears the BGM stream down, so the infolabel goes empty; the resume
    # point has to be the value frozen at suspend time.
    _configure_playlist(tmp_path)

    def clip_starts_and_kodi_forgets_the_index() -> None:
        _clip_starts()
        world.playlist_position = ""

    _run(monkeypatch, [clip_starts_and_kodi_forgets_the_index, _clip_ends_on_an_image])

    assert _resume_calls() == [RESUME_OFFSET]


# -- scenario 2: the clip ends on an image, BGM resumes (FR-003, SC-002) -----


def test_a_clip_ending_resumes_at_the_track_after_the_one_interrupted(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    playlist_path = _configure_playlist(tmp_path)

    _run(monkeypatch, [_clip_starts, _clip_ends_on_an_image])

    assert world.play_media_calls[1] == {
        "path": playlist_path,
        "playoffset": RESUME_OFFSET,
    }


def test_a_clip_ending_returns_the_session_to_playing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)
    session = SlideshowSession()
    seen: List[SessionState] = []

    _drive(
        monkeypatch,
        [
            _noting(_clip_starts, session, seen),
            _noting(_clip_ends_on_an_image, session, seen),
        ],
    )
    session.run()

    assert seen == [SessionState.SUSPENDED, SessionState.PLAYING]


def test_the_resumed_music_fades_in_rather_than_cutting_in(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    fade_requests: List[Tuple[Direction, int, int]],
) -> None:
    _configure_playlist(tmp_path)
    world.volume = 50

    _run(monkeypatch, [_clip_starts, _clip_ends_on_an_image])

    assert fade_requests[2] == (Direction.IN, 50, FADE_DURATION_MS)


def test_the_resume_starts_playback_before_it_fades_anything_in(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)
    recorded: List[List[str]] = []

    def clip_ends_and_we_look_at_the_order() -> None:
        _clip_ends_on_an_image()
        recorded.append(list(world.builtins))

    _run(monkeypatch, [_clip_starts, clip_ends_and_we_look_at_the_order])

    builtins = recorded[0]
    resumed = [
        index
        for index, call in enumerate(builtins)
        if call.startswith("PlayMedia(") and "playoffset" in call
    ]
    faded = [
        index
        for index, call in enumerate(builtins)
        if call.startswith("SetVolume(") and index > resumed[0]
    ]
    assert resumed and faded
    assert resumed[0] < faded[0]


def test_on_playback_ended_resumes_exactly_like_on_playback_stopped(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # contracts/modules.md: the two callbacks are indistinguishable in effect
    # and share one handler. The probe only ever saw onPlayBackStopped (D-001),
    # so onPlayBackEnded is exercised here rather than left to chance.
    _configure_playlist(tmp_path)

    _run(monkeypatch, [_clip_starts, lambda: _clip_ends_on_an_image(ended=True)])

    assert _resume_calls() == [RESUME_OFFSET]


def test_a_single_track_playlist_resumes_into_itself(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FR-003: "the following track" of a one-track playlist is that same
    # track. Nothing special is implemented for it -- the offset runs one past
    # the end and Kodi's own RepeatAll (Assumption 5) wraps it.
    _configure_playlist(tmp_path, tracks=1)

    session = _run(monkeypatch, [_clip_starts, _clip_ends_on_an_image], track=1)

    assert _resume_calls() == [2]
    assert session.state is SessionState.TERMINATED


def test_a_clip_before_any_track_index_was_read_resumes_from_the_start(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # data-model.md's resume algorithm: an invalid index restarts the playlist
    # rather than guessing at a resume point.
    _configure_playlist(tmp_path)

    _run(monkeypatch, [_clip_starts, _clip_ends_on_an_image], track=None)

    assert _resume_calls() == [0]


def test_resuming_from_the_playlist_start_says_so_in_the_log(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)

    _run(monkeypatch, [_clip_starts, _clip_ends_on_an_image], track=None)

    assert _one_log("Playlist.Position(music) unreadable") == (
        "Playlist.Position(music) unreadable; resuming from playlist start",
        xbmc.LOGWARNING,
    )


# -- scenario 3: clips back to back (Edge Case 4, US2 scenario 3) ------------


def test_a_second_clip_back_to_back_leaves_the_session_suspended(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)
    session = SlideshowSession()
    seen: List[SessionState] = []

    _drive(
        monkeypatch,
        [
            _clip_starts,
            _noting(lambda: _clip_starts(SECOND_CLIP), session, seen),
        ],
    )
    session.run()

    assert seen == [SessionState.SUSPENDED]


def test_back_to_back_clips_never_resume_between_themselves(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)

    _run(monkeypatch, [_clip_starts, lambda: _clip_starts(SECOND_CLIP)])

    assert _resume_calls() == []


def test_a_run_of_clips_suspends_once_and_resumes_once(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # US2 scenario 3: music pauses at the first clip, stays paused across all
    # of them, and comes back only when the slideshow reaches an image.
    _configure_playlist(tmp_path)

    _run(
        monkeypatch,
        [
            _clip_starts,
            lambda: _clip_starts(SECOND_CLIP),
            lambda: _clip_starts(CLIP),
            _clip_ends_on_an_image,
        ],
    )

    assert len(_log_entries("BGM suspended for video clip")) == 1
    assert len(_log_entries("BGM resume:")) == 1
    assert _resume_calls() == [RESUME_OFFSET]


def test_a_run_of_clips_resumes_at_the_track_the_first_one_interrupted(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The resume point is frozen once, at the first clip -- later clips must
    # not overwrite it with whatever Kodi reports mid-run.
    _configure_playlist(tmp_path)

    def another_clip_and_a_misleading_infolabel() -> None:
        world.playlist_position = "99"
        _clip_starts(SECOND_CLIP)

    _run(
        monkeypatch,
        [_clip_starts, another_clip_and_a_misleading_infolabel, _clip_ends_on_an_image],
    )

    assert _resume_calls() == [RESUME_OFFSET]


def test_each_extra_clip_is_logged_as_still_suspended_at_debug(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # contracts/logging.md: LOGDEBUG, because a long run of clips would
    # otherwise flood the log at a level users are asked to share.
    _configure_playlist(tmp_path)

    _run(
        monkeypatch,
        [_clip_starts, lambda: _clip_starts(SECOND_CLIP), lambda: _clip_starts(CLIP)],
    )

    assert (
        _log_entries("still suspended")
        == [("still suspended: next slide is a video clip", xbmc.LOGDEBUG)] * 2
    )


def test_a_second_clip_does_not_re_drop_a_volume_already_at_silence(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Edge Case 4: the clip's audio faded in when the first clip started; a
    # second clip must not snap it back to 0 and fade it in all over again.
    _configure_playlist(tmp_path)
    world.volume = 60
    during: List[List[int]] = []

    def another_clip_and_we_watch_the_volume() -> None:
        before = len(world.volume_calls)
        _clip_starts(SECOND_CLIP)
        during.append(_volumes()[before:])

    _run(monkeypatch, [_clip_starts, another_clip_and_we_watch_the_volume])

    assert during == [[]]


# -- FR-004 outranks FR-003 when a clip ends as the slideshow exits ----------


def test_a_clip_ending_as_the_slideshow_closes_does_not_resume(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)

    _run(monkeypatch, [_clip_starts, _clip_ends_as_the_slideshow_closes])

    assert _resume_calls() == []
    assert _log_entries("BGM resume:") == []


def test_a_clip_ending_as_kodi_aborts_does_not_resume(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)

    def kodi_aborts_as_the_clip_ends() -> None:
        world.abort_requested = True
        _clip_ends_on_an_image()

    _run(monkeypatch, [_clip_starts, kodi_aborts_as_the_clip_ends])

    assert _resume_calls() == []
    assert _log_entries("BGM resume:") == []


def test_a_session_that_never_resumed_still_ends_cleanly(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FR-004: the addon's own process still terminates normally; what it must
    # not do is put music back on the way out.
    _configure_playlist(tmp_path)
    world.volume = 55

    session = _run(monkeypatch, [_clip_starts, _clip_ends_as_the_slideshow_closes])

    assert session.state is SessionState.TERMINATED
    assert world.volume == 55
    assert _one_log("session end:")[0].endswith("volume restored to 55")


# -- Edge Case 3: teardown must not touch a clip it does not own -------------


def test_teardown_while_a_clip_is_playing_leaves_the_clip_alone(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # D-001: while SUSPENDED the one player Kodi exposes *is* the slideshow's
    # video clip -- BGM's stream is long gone. Stopping it here would cut the
    # slideshow's own content short as the addon exits.
    _configure_playlist(tmp_path)

    _run(monkeypatch, [_clip_starts])

    assert world.playing == "video"
    assert world.current_file == CLIP


def test_teardown_while_a_clip_is_playing_still_terminates_and_logs(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)
    world.volume = 65

    session = _run(monkeypatch, [_clip_starts])

    assert session.state is SessionState.TERMINATED
    assert _one_log("session end:") == (
        "session end: reason=slideshow_closed volume restored to 65",
        xbmc.LOGINFO,
    )


def test_teardown_while_a_clip_is_playing_restores_the_users_volume(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)
    world.volume = 65

    _run(monkeypatch, [_clip_starts])

    assert world.volume_calls[-1] == (65, False)
    assert world.volume == 65


def test_teardown_while_a_clip_is_playing_fades_nothing_out(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    fade_requests: List[Tuple[Direction, int, int]],
) -> None:
    # There is no background music to fade out (D-001), and ramping the
    # clip's audio down is explicitly excluded by FR-013.
    _configure_playlist(tmp_path)

    _run(monkeypatch, [_clip_starts])

    assert [direction for direction, _, _ in fade_requests] == [
        Direction.IN,
        Direction.IN,
    ]


def test_stopping_bgm_at_teardown_does_not_look_like_a_clip_ending(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Teardown's own stop() fires the same callback a clip does, on this very
    # player. With no clip on screen that reads as "a clip ended", and a
    # handler keyed on anything other than "were we suspended" would answer it
    # by starting music as the addon exits.
    _configure_playlist(tmp_path)

    _run(monkeypatch, [])

    assert len(world.play_media_calls) == 1
    assert _log_entries("BGM resume:") == []
    assert world.playing is None


def test_a_teardown_with_the_slideshow_still_up_does_not_restart_music(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same stop() callback, on the one exit path where the slideshow is
    # still on screen: an exception on the way out. Nothing about the *world*
    # distinguishes this from a clip ending -- only "were we suspended?" does.
    _configure_playlist(tmp_path)
    world.conditions["Slideshow.IsActive"] = True

    def kodi_falls_over(self: Any, timeout: float) -> bool:
        _bgm_actually_starts(TRACK)
        fader.join(JOIN_SECONDS)
        raise RuntimeError("Kodi is shutting down")

    monkeypatch.setattr(xbmc.Monitor, "waitForAbort", kodi_falls_over)
    session = SlideshowSession()

    with pytest.raises(RuntimeError):
        session.run()

    assert world.conditions["Slideshow.IsActive"] is True
    assert len(world.play_media_calls) == 1
    assert _log_entries("BGM resume:") == []
    assert session.state is SessionState.TERMINATED


def test_a_callback_arriving_after_the_session_ended_changes_nothing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FR-004/Edge Case 3: TERMINATED is absorbing. The player object outlives
    # run(), and a slideshow that carries on from one clip to the next still
    # delivers onPlayBackStopped to it (D-001). Handling that would snap the
    # volume to 0 again -- after teardown had already restored it.
    _configure_playlist(tmp_path)
    world.volume = 55

    session = _run(monkeypatch, [_clip_starts])
    settled = list(world.volume_calls)
    _clip_starts(SECOND_CLIP)
    _clip_ends_on_an_image()

    assert session.state is SessionState.TERMINATED
    assert world.volume_calls == settled
    assert world.volume == 55
    assert len(world.play_media_calls) == 1


def test_the_clips_own_av_started_does_not_move_the_resume_point(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # onAVStarted fires for the slideshow's own clips too -- that callback is
    # what the probe measured clip-start latency with. Playlist.Position(music)
    # does not describe a clip, so reading it there would move the resume
    # point (contracts/modules.md: every handler checks Slideshow.IsVideo).
    _configure_playlist(tmp_path)

    def the_clips_audio_starts() -> None:
        _clip_starts()
        world.playlist_position = "99"
        world.fire_av_started()

    _run(monkeypatch, [the_clips_audio_starts, _clip_ends_on_an_image])

    assert _resume_calls() == [RESUME_OFFSET]
    assert _log_entries("Playlist.Position(music) unreadable") == []


# -- FR-016: the user's own volume change survives a whole cycle -------------


def test_a_volume_change_before_a_clip_becomes_the_resume_and_restore_target(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    fade_requests: List[Tuple[Direction, int, int]],
) -> None:
    # FR-016/D-012: the level re-observed at the PLAYING -> SUSPENDED
    # transition is what every later fade ramps toward and what teardown
    # restores -- not the level captured at session start.
    _configure_playlist(tmp_path)
    world.volume = 30

    def the_user_turns_it_up() -> None:
        world.volume = 90

    _run(monkeypatch, [the_user_turns_it_up, _clip_starts, _clip_ends_on_an_image])

    assert [baseline for _, baseline, _ in fade_requests] == [30, 90, 90, 90]
    assert world.volume == 90
    assert world.volume_calls[-1] == (90, False)
    assert _one_log("session end:")[0].endswith("volume restored to 90")


# -- FR-009 log lines (contracts/logging.md) ---------------------------------


def test_the_suspend_line_names_the_track_that_was_interrupted(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)

    _run(monkeypatch, [_clip_starts])

    assert _one_log("BGM suspended") == (
        "BGM suspended for video clip at track={0}".format(TRACK),
        xbmc.LOGINFO,
    )


def test_the_resume_line_names_the_new_track_and_the_one_it_replaces(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_playlist(tmp_path)

    _run(monkeypatch, [_clip_starts, _clip_ends_on_an_image])

    assert _one_log("BGM resume:") == (
        "BGM resume: track={0} (was {1})".format(RESUME_OFFSET, TRACK),
        xbmc.LOGINFO,
    )


def test_a_suspend_and_resume_cycle_never_asks_for_the_volume_bar(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # R-2 regression guard across the transitions US2 adds (D-013).
    _configure_playlist(tmp_path)
    world.volume = 70

    _run(monkeypatch, [_clip_starts, _clip_ends_on_an_image])

    assert len(world.volume_calls) > 4
    assert [shown for _, shown in world.volume_calls] == [False] * len(
        world.volume_calls
    )
