"""Start background music and track which item is playing (FR-001, D-005, D-006).

Playback is started with the ``PlayMedia`` builtin rather than
``xbmc.Player.play()`` (D-006). By the time this module ever sees a path, it
is always a plain ``.m3u`` -- ``.pls``/``.xsp`` sources are resolved to one by
``playlist.py`` first (R-8, added 2026-09-14): real-device testing found
Kodi's own ``playoffset`` never advances past track 1 for those two formats,
so this module's resume arithmetic below only ever has to work against the
one format it is proven to work for. This module itself still never branches
on source format.

The order in :meth:`BgmPlayer.start` is fixed by D-006 and is not cosmetic:
``PlayerControl(RandomOn|RandomOff|RepeatAll)`` only take effect while a player
is active, so playback MUST be established first and the controls applied
immediately after -- with the fade-in held until they are in place, so the user
never hears an unshuffled first moment.

The current track index is read from Kodi's own infolabel inside
``onAVStarted`` (D-005), never polled and never counted internally. The index
is recorded exactly as Kodi reports it: the probe (2026-09-13, Kodi 21.3)
confirmed ``Playlist.Position(music)`` is **1-indexed**. The only ``+1`` in
this module is :func:`resume_offset`, the resume target FR-003 asks for.

``onPlayBackStopped`` and ``onPlayBackEnded`` share one handler because they
are indistinguishable in effect (contracts/modules.md): the probe saw only
``onPlayBackStopped`` when a clip claimed the player, but which one Kodi picks
is not a fact this addon may rely on. The handler does not interpret the event
-- it establishes whether a clip is on screen (``Slideshow.IsVideo``) and
reports "a clip started" or "a clip ended" to the two callables its owner
passed in. What those mean for the session's state machine is
``session.py``'s business; deciding it here would mean importing the owner,
closing the cycle contracts/modules.md's dependency graph forbids.
"""

from typing import Callable, NamedTuple

import xbmc

from resources.lib import fader, messages
from resources.lib.fader import Direction

PLAYLIST_POSITION_INFOLABEL = "Playlist.Position(music)"
PLAYLIST_LENGTH_INFOLABEL = "Playlist.Length(music)"

SLIDESHOW_IS_VIDEO_CONDITION = "Slideshow.IsVideo"

#: ``playoffset`` used when no usable track index was ever recorded: restart
#: the playlist rather than guess at a resume point (D-004, data-model.md).
PLAYLIST_START_OFFSET = 0


class BgmPosition(NamedTuple):
    """Which BGM track is playing (data-model.md ``BgmPosition``).

    Attributes:
        track_index: The index Kodi reported, verbatim and 1-indexed (D-005).
        track_count: The playlist length Kodi reported, or ``0`` when it was
            never read or the read failed -- mirroring how ``track_index=0``
            marks :data:`UNKNOWN_POSITION`'s "nothing read yet" state.
        is_valid: False before the first ``onAVStarted``, and whenever the
            position infolabel read failed.
    """

    track_index: int
    track_count: int
    is_valid: bool


#: What :attr:`BgmPlayer.position` holds before any usable read (D-005).
UNKNOWN_POSITION = BgmPosition(track_index=0, track_count=0, is_valid=False)


def resume_offset(position: BgmPosition) -> int:
    """Which playlist entry a resume from ``position`` targets (FR-003, D-004).

    One path for every source: the track *after* the interrupted one, from its
    beginning. T041 proved ``PlayMedia``'s ``playoffset`` does not wrap past
    the end of a playlist the way ``PlayerControl(RepeatAll)`` wraps a track
    that finishes naturally -- Kodi's own source (``PlayerBuiltins.cpp``)
    clamps an out-of-range ``playoffset`` to the last track and replays it,
    forever. So the addon computes the wrap itself from ``track_count``
    (``Playlist.Length(music)``, read alongside ``track_index`` in
    ``onAVStarted``): the last track resumes into track 1.

    Args:
        position: The resume point frozen when a clip claimed the player.

    Returns:
        The ``playoffset`` to hand ``PlayMedia``: ``track_index + 1``, wrapped
        to ``1`` when that would exceed ``track_count``; or
        :data:`PLAYLIST_START_OFFSET` when no usable index was ever recorded.
        When ``track_count`` itself is unknown, falls back to the unwrapped
        ``track_index + 1`` -- no regression versus today, since Kodi already
        clamps at the boundary regardless.
    """
    if not position.is_valid:
        return PLAYLIST_START_OFFSET
    next_index = position.track_index + 1
    if position.track_count > 0 and next_index > position.track_count:
        return 1
    return next_index


# ``type: ignore[misc]`` -- Kodistubs ships no ``py.typed`` marker, so mypy
# resolves ``xbmc`` to ``Any`` (see pyproject.toml's mypy override) and
# ``--strict`` refuses to subclass it. Subclassing ``xbmc.Player`` is the only
# way Kodi delivers playback callbacks, so the alternative is not subclassing
# at all.
class BgmPlayer(xbmc.Player):  # type: ignore[misc]
    """Kodi player bound to this slideshow's background music.

    Attributes:
        position: The :class:`BgmPosition` last reported by ``onAVStarted``.
            Public on purpose -- it is the resume point the session freezes
            when a clip interrupts.
    """

    def __init__(
        self, on_clip_start: Callable[[], None], on_clip_end: Callable[[], None]
    ) -> None:
        """Register with Kodi and start out with no known track position.

        Args:
            on_clip_start: Called when a playback callback arrives while a
                slideshow video clip is on screen.
            on_clip_end: Called when one arrives while it is not. Both are
                plain callables rather than a session reference, so this
                module never imports its owner (contracts/modules.md).
        """
        super().__init__()
        self.position: BgmPosition = UNKNOWN_POSITION
        self._on_clip_start = on_clip_start
        self._on_clip_end = on_clip_end
        self._playlist = ""

    def start(self, playlist: str, shuffle: bool) -> None:
        """Begin background music and fade it in (FR-001, FR-008, FR-013).

        Args:
            playlist: Absolute path of the playlist to hand to ``PlayMedia``.
                Remembered so :meth:`resume_at` can replay the same one.
            shuffle: Whether to play in random order. Ignored by Kodi for
                ``.pls``/``.xsp``, which keep their native order (FR-008).
        """
        self._playlist = playlist
        xbmc.executebuiltin("PlayMedia({0})".format(playlist))
        xbmc.executebuiltin(
            "PlayerControl(RandomOn)" if shuffle else "PlayerControl(RandomOff)"
        )
        # Assumption 5: BGM loops rather than ending before the slideshow.
        xbmc.executebuiltin("PlayerControl(RepeatAll)")
        fader.fade(Direction.IN, fader.capture_baseline())

    def resume_at(self, position: BgmPosition) -> None:
        """Replay from the track after ``position`` and fade in (FR-003).

        One path for every source -- no seek, no offset within a track, no
        per-format branch (D-004). The baseline is re-read here rather than
        reused from before the clip, so a volume change made in the meantime
        is what the fade ramps toward (FR-016, D-012).

        Args:
            position: The resume point frozen when the clip claimed the
                player. An invalid one restarts the playlist instead of
                guessing, which is worth a warning: it is audible.
        """
        offset = resume_offset(position)
        if not position.is_valid:
            messages.log(
                "Playlist.Position(music) unreadable; resuming from playlist start",
                xbmc.LOGWARNING,
            )
        xbmc.executebuiltin(
            "PlayMedia({0},playoffset={1})".format(self._playlist, offset)
        )
        fader.fade(Direction.IN, fader.capture_baseline())

    def onPlayBackStopped(self) -> None:
        """Kodi stopped playback -- see :meth:`_on_playback_interrupted`."""
        self._on_playback_interrupted()

    def onPlayBackEnded(self) -> None:
        """Kodi ended playback -- see :meth:`_on_playback_interrupted`."""
        self._on_playback_interrupted()

    def _on_playback_interrupted(self) -> None:
        """Report a playback callback as a clip start or a clip end (D-001).

        The one shared handler both callbacks are contractually required to
        use. It decides nothing beyond what is on screen *now*: a clip means
        "a clip is playing", anything else means "no clip is playing", and
        what either implies for a session that may already be suspended --
        or already torn down -- belongs to the owner these callables came
        from.
        """
        if xbmc.getCondVisibility(SLIDESHOW_IS_VIDEO_CONDITION):
            self._on_clip_start()
        else:
            self._on_clip_end()

    def onAVStarted(self) -> None:
        """Record the track index Kodi reports for the new item (D-005).

        Ignored while a slideshow video clip is on screen: the callback fires
        for the slideshow's own clips too, and ``Playlist.Position(music)``
        does not describe them (contracts/modules.md). Reading it there would
        overwrite the resume point with a clip's index -- or invalidate it and
        log a warning about an index nothing was asking for.

        ``getInfoLabel`` returns a string -- empty when nothing is playing --
        so the conversion is guarded and a failed read leaves the position
        invalid rather than stale.
        """
        if xbmc.getCondVisibility(SLIDESHOW_IS_VIDEO_CONDITION):
            return
        raw = xbmc.getInfoLabel(PLAYLIST_POSITION_INFOLABEL)
        try:
            track_index = int(raw)
        except (TypeError, ValueError):
            self.position = UNKNOWN_POSITION
            messages.log(
                "Playlist.Position(music) unreadable; resuming from playlist start",
                xbmc.LOGWARNING,
            )
            return
        # track_count falls back to 0 (unknown) when unreadable -- resume_offset
        # then falls back to its own non-wrapping behavior; nothing here needs
        # to invalidate a position read that otherwise succeeded.
        try:
            track_count = int(xbmc.getInfoLabel(PLAYLIST_LENGTH_INFOLABEL))
        except (TypeError, ValueError):
            track_count = 0
        self.position = BgmPosition(
            track_index=track_index, track_count=track_count, is_valid=True
        )
