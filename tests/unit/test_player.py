"""Tests for resources/lib/player.py (FR-001..FR-003, FR-008, FR-013, D-001,
D-004, D-005, D-006)."""

from typing import Iterator, List, Optional, Tuple

import pytest
import xbmc

from resources.lib import fader, messages
from resources.lib.player import UNKNOWN_POSITION, BgmPlayer, BgmPosition, resume_offset

world = xbmc.world

PLAYLIST = "/music/bgm.m3u"
JOIN_SECONDS = 2.0


@pytest.fixture(autouse=True)
def _stop_ramps_between_tests() -> Iterator[None]:
    """Never let a ramp from one test bleed volume calls into the next."""
    yield
    fader.cancel()
    fader.join(JOIN_SECONDS)


def _player(events: Optional[List[str]] = None) -> BgmPlayer:
    """A player whose clip callbacks append their name to ``events``.

    The callbacks are how the player reports clip transitions to whoever owns
    it without importing that owner (contracts/modules.md); a list of names is
    the whole of what the player is contractually allowed to know about them.
    """
    recorded = events if events is not None else []
    return BgmPlayer(
        lambda: recorded.append("clip start"), lambda: recorded.append("clip end")
    )


def _log_entries(prefix: str) -> List[Tuple[str, int]]:
    header = messages.LOG_HEADER
    return [
        (message[len(header) :], level)
        for message, level in world.log_lines
        if message.startswith(header + prefix)
    ]


# -- start (FR-001, FR-008, D-006) -------------------------------------------


def test_start_hands_the_playlist_to_playmedia() -> None:
    _player().start(PLAYLIST, shuffle=False)

    assert world.play_media_calls == [{"path": PLAYLIST, "playoffset": None}]


def test_start_primes_shuffle_on_when_asked() -> None:
    _player().start(PLAYLIST, shuffle=True)

    assert "PlayerControl(RandomOn)" in world.builtins
    assert "PlayerControl(RandomOff)" not in world.builtins


def test_start_primes_shuffle_off_when_not_asked() -> None:
    _player().start(PLAYLIST, shuffle=False)

    assert "PlayerControl(RandomOff)" in world.builtins
    assert "PlayerControl(RandomOn)" not in world.builtins


def test_start_always_primes_repeat_so_bgm_loops() -> None:
    # Assumption 5: BGM loops rather than ending before the slideshow does.
    _player().start(PLAYLIST, shuffle=False)

    assert "PlayerControl(RepeatAll)" in world.builtins


def test_start_establishes_playback_before_priming_the_controls() -> None:
    # D-006: PlayerControl only takes effect while a player is active.
    _player().start(PLAYLIST, shuffle=True)

    assert world.builtins[0].startswith("PlayMedia(")
    assert world.builtins[1].startswith("PlayerControl(")


def test_start_holds_the_fade_in_until_the_controls_are_primed() -> None:
    # D-006: the user must never hear an unshuffled first moment.
    _player().start(PLAYLIST, shuffle=True)

    primed = [
        index
        for index, call in enumerate(world.builtins)
        if call.startswith("PlayerControl(")
    ]
    faded = [
        index
        for index, call in enumerate(world.builtins)
        if call.startswith("SetVolume(")
    ]
    assert primed and faded
    assert max(primed) < min(faded)


def test_start_fades_in_from_silence_to_the_current_volume() -> None:
    world.volume = 44

    _player().start(PLAYLIST, shuffle=False)
    assert fader.join(JOIN_SECONDS) is True

    volumes = [percent for percent, _ in world.volume_calls]
    assert volumes[0] == 0
    assert volumes[-1] == 44
    assert volumes == sorted(volumes)


def test_start_never_asks_kodi_to_show_the_volume_bar() -> None:
    # R-2 regression guard (D-013).
    world.volume = 44

    _player().start(PLAYLIST, shuffle=False)
    fader.join(JOIN_SECONDS)

    assert [shown for _, shown in world.volume_calls] == [False] * len(
        world.volume_calls
    )


# -- onAVStarted (D-005) -----------------------------------------------------


def test_a_fresh_player_has_no_valid_position_yet() -> None:
    player = _player()

    assert player.position.is_valid is False


def test_on_av_started_records_the_index_kodi_reports_verbatim() -> None:
    # D-005: the infolabel is 1-indexed; it is recorded as read, and any
    # resume arithmetic belongs to whoever computes a resume target (US2).
    player = _player()
    world.playlist_position = "1"

    world.fire_av_started()

    assert player.position.track_index == 1
    assert player.position.is_valid is True


def test_on_av_started_records_a_later_track_index() -> None:
    player = _player()
    world.playlist_position = "7"

    world.fire_av_started()

    assert player.position == (7, 0, True)


def test_on_av_started_records_the_playlist_length_kodi_reports() -> None:
    player = _player()
    world.playlist_position = "3"
    world.playlist_length = "10"

    world.fire_av_started()

    assert player.position.track_count == 10


def test_an_empty_playlist_length_leaves_the_track_count_unknown() -> None:
    # An unreadable Playlist.Length(music) must not invalidate a perfectly
    # readable Playlist.Position(music) -- only resume_offset's wrap needs it.
    player = _player()
    world.playlist_position = "3"
    assert world.playlist_length == ""

    world.fire_av_started()

    assert player.position.is_valid is True
    assert player.position.track_count == 0


def test_an_empty_infolabel_leaves_the_position_invalid() -> None:
    player = _player()
    assert world.playlist_position == ""

    world.fire_av_started()

    assert player.position.is_valid is False


def test_a_non_numeric_infolabel_leaves_the_position_invalid() -> None:
    player = _player()
    world.playlist_position = "not a number"

    world.fire_av_started()

    assert player.position.is_valid is False


def test_an_unreadable_infolabel_is_logged_as_a_warning() -> None:
    _player()

    world.fire_av_started()

    assert _log_entries("Playlist.Position(music) unreadable") == [
        (
            "Playlist.Position(music) unreadable; resuming from playlist start",
            xbmc.LOGWARNING,
        )
    ]


def test_a_readable_index_is_not_logged_as_a_warning() -> None:
    _player()
    world.playlist_position = "2"

    world.fire_av_started()

    assert _log_entries("Playlist.Position(music) unreadable") == []


def test_an_unreadable_read_invalidates_a_previously_recorded_index() -> None:
    player = _player()
    world.playlist_position = "3"
    world.fire_av_started()

    world.playlist_position = ""
    world.fire_av_started()

    assert player.position.is_valid is False


def test_on_av_started_ignores_the_slideshows_own_video_clips() -> None:
    # contracts/modules.md: every handler must first establish whether the
    # event concerns BGM or a slide. Playlist.Position(music) says nothing
    # about a clip, so reading it here would move the resume point.
    player = _player()
    world.playlist_position = "3"
    world.fire_av_started()

    world.conditions["Slideshow.IsVideo"] = True
    world.playlist_position = "99"
    world.fire_av_started()

    assert player.position == (3, 0, True)


def test_a_clips_av_started_is_not_reported_as_an_unreadable_index() -> None:
    # The infolabel goes empty once the clip tears the BGM stream down
    # (D-001). Warning about that would be a warning about nothing.
    _player()
    world.conditions["Slideshow.IsVideo"] = True

    world.fire_av_started()

    assert _log_entries("Playlist.Position(music) unreadable") == []


# -- the shared playback callback (D-001, contracts/modules.md) --------------


def test_a_playback_callback_with_a_clip_on_screen_reports_a_clip_start() -> None:
    events: List[str] = []
    _player(events)

    world.conditions["Slideshow.IsVideo"] = True
    world.fire_stopped()

    assert events == ["clip start"]


def test_a_playback_callback_with_no_clip_on_screen_reports_a_clip_end() -> None:
    events: List[str] = []
    _player(events)

    world.fire_stopped()

    assert events == ["clip end"]


def test_on_playback_ended_shares_the_handler_with_on_playback_stopped() -> None:
    # The probe only ever saw onPlayBackStopped for a clip interruption
    # (D-001), but which one Kodi picks is not a fact this addon may rely on.
    events: List[str] = []
    _player(events)

    world.conditions["Slideshow.IsVideo"] = True
    world.fire_ended()
    world.conditions["Slideshow.IsVideo"] = False
    world.fire_ended()

    assert events == ["clip start", "clip end"]


def test_the_player_reports_clip_events_without_interpreting_them() -> None:
    # Back-to-back clips are Edge Case 4, and what they mean is the session's
    # business: the player reports every callback as it comes.
    events: List[str] = []
    _player(events)
    world.conditions["Slideshow.IsVideo"] = True

    world.fire_stopped()
    world.fire_stopped()

    assert events == ["clip start", "clip start"]


# -- resume_offset / resume_at (FR-003, D-004) ------------------------------


def test_the_resume_target_is_the_track_after_the_one_interrupted() -> None:
    assert resume_offset(BgmPosition(track_index=3, track_count=10, is_valid=True)) == 4


def test_a_one_track_playlist_wraps_to_its_own_start() -> None:
    # T041 (real device + PlayerBuiltins.cpp): playoffset past the end does
    # NOT wrap -- Kodi clamps to the last track and replays it forever. A
    # genuine one-track playlist must wrap itself back to offset 1.
    assert resume_offset(BgmPosition(track_index=1, track_count=1, is_valid=True)) == 1


def test_resuming_from_the_last_track_of_a_known_playlist_wraps_to_the_start() -> None:
    assert (
        resume_offset(BgmPosition(track_index=10, track_count=10, is_valid=True)) == 1
    )


def test_resuming_from_a_non_last_track_of_a_known_playlist_just_advances() -> None:
    assert resume_offset(BgmPosition(track_index=3, track_count=10, is_valid=True)) == 4


def test_an_unreadable_track_count_falls_back_to_the_non_wrapping_offset() -> None:
    # T041: an unreadable Playlist.Length(music) must not invent a new failure
    # mode -- Kodi already clamps at the boundary regardless, so this matches
    # today's (pre-fix) behavior rather than risk a wrong wrap.
    position = BgmPosition(track_index=10, track_count=0, is_valid=True)
    assert resume_offset(position) == 11


def test_an_unknown_position_resumes_from_the_playlist_start() -> None:
    assert resume_offset(UNKNOWN_POSITION) == 0


def test_resume_at_replays_the_playlist_start_gave_it() -> None:
    player = _player()
    player.start(PLAYLIST, shuffle=False)

    player.resume_at(BgmPosition(track_index=3, track_count=10, is_valid=True))

    assert world.play_media_calls[-1] == {"path": PLAYLIST, "playoffset": 4}


def test_resume_at_falls_back_to_the_playlist_start_when_asked_for_nothing() -> None:
    player = _player()
    player.start(PLAYLIST, shuffle=False)

    player.resume_at(UNKNOWN_POSITION)

    assert world.play_media_calls[-1] == {"path": PLAYLIST, "playoffset": 0}


def test_resume_at_warns_when_it_falls_back_to_the_playlist_start() -> None:
    player = _player()
    player.start(PLAYLIST, shuffle=False)

    player.resume_at(UNKNOWN_POSITION)

    assert _log_entries("Playlist.Position(music) unreadable") == [
        (
            "Playlist.Position(music) unreadable; resuming from playlist start",
            xbmc.LOGWARNING,
        )
    ]


def test_resume_at_does_not_warn_when_it_has_a_usable_index() -> None:
    player = _player()
    player.start(PLAYLIST, shuffle=False)

    player.resume_at(BgmPosition(track_index=2, track_count=10, is_valid=True))

    assert _log_entries("Playlist.Position(music) unreadable") == []


def test_resume_at_fades_in_from_silence_to_the_current_volume() -> None:
    # FR-016/D-012: the level is re-read here, so a change the user made while
    # the clip was playing is what the music comes back to.
    player = _player()
    player.start(PLAYLIST, shuffle=False)
    fader.join(JOIN_SECONDS)
    world.volume = 77

    player.resume_at(BgmPosition(track_index=2, track_count=10, is_valid=True))
    assert fader.join(JOIN_SECONDS) is True

    resumed = world.builtins.index("PlayMedia({0},playoffset=3)".format(PLAYLIST))
    volumes = [
        int(call[len("SetVolume(") : -1])
        for call in world.builtins[resumed:]
        if call.startswith("SetVolume(")
    ]
    assert volumes[0] == 0
    assert volumes[-1] == 77
    assert volumes == sorted(volumes)


def test_resume_at_starts_playback_before_it_fades_anything_in() -> None:
    player = _player()
    player.start(PLAYLIST, shuffle=False)
    fader.join(JOIN_SECONDS)
    before = len(world.builtins)

    player.resume_at(BgmPosition(track_index=2, track_count=10, is_valid=True))

    assert world.builtins[before].startswith("PlayMedia(")
