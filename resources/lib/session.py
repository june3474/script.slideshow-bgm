"""Own one slideshow's BGM lifecycle, start to teardown (FR-004, D-002).

The session is the only object that decides whether background music happens
at all: it resolves the configured source, claims (or yields) Kodi's player,
starts playback, waits out the slideshow on an abort-aware ``Monitor`` wait,
and tears everything down again on every exit path.

Every transition in data-model.md's state machine is implemented here. The
session is also the only place the ``PLAYING <-> SUSPENDED`` half can live:
:class:`~resources.lib.player.BgmPlayer` reports *events* ("a clip is on
screen", "none is") and this class alone knows what they mean for the state
machine, which is what keeps ``player.py`` from importing its own owner
(contracts/modules.md's dependency graph).

Three contracts drive the teardown order:

- The player is stopped only from ``PLAYING``. While ``SUSPENDED`` the thing
  ``xbmc.Player()`` stands for is the *slideshow's* video clip -- the BGM
  stream was destroyed when that clip claimed the player (D-001), so there is
  nothing of this addon's left to stop and stopping anyway would cut the
  slideshow's own clip short (Edge Case 3).

- The fade-out is awaited *before* the player is stopped. Stopping first would
  leave a ramp shaping silence, which is exactly what FR-013 exists to
  prevent; SC-003's 2-second budget is written as "detection (up to 0.5 s)
  plus the full 1-second fade-out", so the ramp is meant to finish while
  music is still playing.
- ``session end`` is logged, and the user's volume restored, on *every* exit
  path -- which is why the whole body of :meth:`SlideshowSession.run` sits in
  a ``try``/``finally`` (D-003, contracts/logging.md).
"""

import enum
from typing import Optional

import xbmc
import xbmcgui

from resources import lib
from resources.lib import config, fader, messages, playlist
from resources.lib.config import Policy, Reason
from resources.lib.fader import Direction
from resources.lib.player import (
    UNKNOWN_POSITION,
    BgmPlayer,
    BgmPosition,
    resume_offset,
)
from resources.lib.playlist import BgmSource

#: Longest wait interval that still leaves headroom inside SC-003's 2 s
#: teardown budget (research.md D-002) -- fixed by that budget, not tunable.
WAIT_INTERVAL_SECONDS = 0.5

#: How long teardown waits for the fade thread before abandoning it. Longer
#: than FR-013's 1 s ramp, short enough that a hung ramp cannot hold the
#: process open (constitution 2.1, FR-004).
FADE_JOIN_TIMEOUT_SECONDS = 2.0

SLIDESHOW_ACTIVE_CONDITION = "Slideshow.IsActive"
SLIDESHOW_PAUSED_CONDITION = "Slideshow.IsPaused"

REASON_SLIDESHOW_CLOSED = "slideshow_closed"
REASON_ABORT_REQUESTED = "abort_requested"
REASON_EXISTING_PLAYBACK = "existing playback (policy=Yield)"

UNKNOWN_TRACK = "unknown"

STRING_BGM_UNAVAILABLE = 32004
STRING_XSP_NOT_MUSIC_PLAYLIST = 32005


class SessionState(enum.Enum):
    """One slideshow session's lifecycle state (data-model.md).

    Attributes:
        STARTING: Session created; source not yet resolved.
        PLAYING: Background music is audible.
        SUSPENDED: A video clip is playing; background music is silent.
        DISABLED: No usable source; the slideshow proceeds without BGM.
        TERMINATED: The slideshow has exited. Absorbing -- BGM never resumes.
    """

    STARTING = "STARTING"
    PLAYING = "PLAYING"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"
    TERMINATED = "TERMINATED"


def _track_label(position: BgmPosition) -> str:
    """Render a track index for the log (contracts/logging.md).

    Args:
        position: The player's current position.

    Returns:
        The index as text, or ``"unknown"`` when Kodi has not reported one
        yet -- ``PlayMedia`` is asynchronous, so the first ``onAVStarted``
        normally lands after ``BGM start`` is logged.
    """
    return str(position.track_index) if position.is_valid else UNKNOWN_TRACK


class SlideshowSession:
    """Owns every object for one slideshow run (data-model.md).

    Attributes:
        state: The current :class:`SessionState`.
        source: The resolved BGM source, or None once BGM is disabled.
        baseline_volume: Volume level fades ramp toward and restore to
            (FR-016); None until first captured, and None for a session that
            never made a sound -- nothing to restore means nothing was
            altered.
        existing_playback_policy: What to do about audio already playing at
            session start (FR-014).
        player: The :class:`BgmPlayer` owning BGM playback, or None while BGM
            is disabled.
        position: The track frozen when a video clip interrupted BGM -- the
            point a resume is computed from (FR-003).
        monitor: Kodi's abort monitor, consulted by the wait loop and again
            before any resume (FR-004).
        end_reason: Why the session ended, as logged by ``session end``.
    """

    def __init__(self) -> None:
        """Create a session in its initial, unstarted state."""
        self.state: SessionState = SessionState.STARTING
        self.source: Optional[BgmSource] = None
        self.baseline_volume: Optional[int] = None
        self.existing_playback_policy: Policy = Policy.TAKE_OVER
        self.player: Optional[BgmPlayer] = None
        self.position: BgmPosition = UNKNOWN_POSITION
        self.monitor = xbmc.Monitor()
        self.end_reason: str = REASON_SLIDESHOW_CLOSED

    def is_slideshow_active(self) -> bool:
        """Whether Kodi's slideshow window is currently showing (D-002).

        Returns:
            True while ``Slideshow.IsActive`` holds; there is no event for
            this window closing, so callers must poll it.
        """
        return bool(xbmc.getCondVisibility(SLIDESHOW_ACTIVE_CONDITION))

    def is_slideshow_paused(self) -> bool:
        """Whether Kodi's own slideshow window is paused, apart from BGM.

        Returns:
            True while ``Slideshow.IsPaused`` holds. A forcibly-skipped video
            clip leaves this set with nothing else in Kodi to clear it
            (``GUIWindowSlideShow``'s ``GUI_MSG_PLAYBACK_STOPPED`` handler sets
            it and stops there, unlike ``_ENDED``, which clears it itself) --
            source-verified 2026-09-17, see research.md.
        """
        return bool(xbmc.getCondVisibility(SLIDESHOW_PAUSED_CONDITION))

    def run(self) -> None:
        """Own the whole lifecycle: start, wait loop, teardown.

        Teardown runs in a ``finally`` so the user's volume is restored and
        ``session end`` logged however this returns -- slideshow closed, Kodi
        aborting, or an exception on the way through (D-003).
        """
        try:
            self._start()
            self._wait()
        finally:
            self._teardown()

    def _start(self) -> None:
        """Take ``STARTING`` to either ``PLAYING`` or ``DISABLED``.

        Every failure is a ``DISABLED`` transition, never an exception: a
        source that cannot be played must not fail the slideshow (FR-010).
        """
        source = config.read_source()
        if source is None:
            # Nothing configured at all: US1 scenario 3 wants the slideshow to
            # proceed with no error shown -- log only, no notification.
            self._disable(Reason.NOT_SELECTED.value, notify=False)
            return
        messages.log(
            "session start: version={0} source={1}:{2} shuffle={3}".format(
                lib.addon_version, source.kind.value, source.path, source.shuffle
            )
        )
        result = config.validate(source)
        if not result.ok:
            if result.reason is Reason.NOT_MUSIC_PLAYLIST:
                self._disable(
                    _reason_of(result.reason),
                    notify=True,
                    message=lib.addon.getLocalizedString(STRING_XSP_NOT_MUSIC_PLAYLIST),
                    icon=xbmcgui.NOTIFICATION_ERROR,
                )
            else:
                self._disable(_reason_of(result.reason), notify=True)
            return
        if not self._claim_the_player():
            self._disable(REASON_EXISTING_PLAYBACK, notify=False)
            return
        resolved = playlist.resolve(source)
        if resolved is None:
            self._disable(Reason.EMPTY.value, notify=True)
            return
        self._play(source, resolved)

    def _claim_the_player(self) -> bool:
        """Decide what to do about audio already playing (FR-014).

        Returns:
            True when BGM may start -- nothing was playing, or the
            ``TakeOver`` policy applied and that playback has been stopped.
            False when the ``Yield`` policy leaves existing playback alone.
        """
        self.existing_playback_policy = config.existing_playback_policy()
        player = xbmc.Player()
        if not player.isPlayingAudio():
            return True
        if self.existing_playback_policy is Policy.YIELD:
            return False
        player.stop()
        return True

    def _play(self, source: BgmSource, resolved: str) -> None:
        """Enter ``PLAYING``: capture the baseline, then start BGM (FR-001).

        The baseline is read before anything fades, since the first fade-in
        snaps the volume to silence and a later read would capture that.

        Args:
            source: The validated source this session plays.
            resolved: Absolute path of the playlist to hand to Kodi.
        """
        self.source = source
        self.baseline_volume = fader.capture_baseline()
        self.player = BgmPlayer(self._on_clip_start, self._on_clip_end)
        self.player.start(resolved, source.shuffle)
        self.state = SessionState.PLAYING
        messages.log("BGM start: track={0}".format(_track_label(self.player.position)))

    def _disable(
        self,
        reason: str,
        notify: bool,
        message: Optional[str] = None,
        icon: str = xbmcgui.NOTIFICATION_INFO,
    ) -> None:
        """Enter ``DISABLED``: the slideshow proceeds silently (FR-010).

        Args:
            reason: Why BGM is off, as logged by ``BGM disabled``.
            notify: Whether to show FR-012's non-blocking notification. Never
                a blocking dialog -- that surface belongs to settings time
                (FR-011), where nothing is interrupted.
            message: Notification text; defaults to the generic "unavailable"
                string when the caller has nothing more specific to say.
            icon: Notification severity icon (FR-012); defaults to
                informational.
        """
        self.state = SessionState.DISABLED
        self.source = None
        messages.log("BGM disabled: {0}".format(reason))
        if notify:
            text = message or lib.addon.getLocalizedString(STRING_BGM_UNAVAILABLE)
            messages.notify(text, icon)

    def _on_clip_start(self) -> None:
        """A slideshow video clip is on screen (``PLAYING -> SUSPENDED``).

        The clip has already destroyed the BGM stream by the time this runs
        (D-001), so there is nothing to stop -- only a resume point to freeze
        and the volume to deal with. ``capture_baseline`` runs *before* the
        drop to silence, or the fade would ramp the clip's audio toward the
        zero it just wrote (FR-016, D-012); the drop itself is inline inside
        ``fader.fade``, which is what keeps it ahead of the clip becoming
        audible (risk R-6).

        A second clip arriving while already suspended is Edge Case 4: stay
        silent, keep the original resume point, and do not re-drop a volume
        that is already where it belongs.
        """
        if self.state is SessionState.SUSPENDED:
            messages.log("still suspended: next slide is a video clip", xbmc.LOGDEBUG)
            return
        if self.state is not SessionState.PLAYING or self.player is None:
            return
        # effective_baseline, not capture_baseline: a clip starting during the
        # initial fade-in must not re-baseline onto a mid-ramp sample (FR-016).
        self.baseline_volume = fader.effective_baseline()
        self.position = self.player.position
        self.state = SessionState.SUSPENDED
        fader.fade(Direction.IN, self.baseline_volume)
        messages.log(
            "BGM suspended for video clip at track={0}".format(
                _track_label(self.position)
            )
        )

    def _on_clip_end(self) -> None:
        """No clip is on screen (``SUSPENDED -> PLAYING``), or nothing to do.

        Callbacks arrive for plenty of events that are not a clip ending --
        including this session's own ``stop()`` during teardown -- so anything
        outside ``SUSPENDED`` is a no-op by design, not by accident.

        FR-004 outranks FR-003 where they collide: a clip ending at the
        instant the slideshow exits must not put music back, so the resume is
        skipped entirely rather than started and torn down.

        A forcibly-skipped clip (as opposed to one left to end naturally)
        leaves Kodi's own slideshow paused with nothing else to unpause it
        (``is_slideshow_paused``), so that is cleared here too -- otherwise
        the picture the user skipped to is the last one the slideshow ever
        shows, even though BGM resumes normally.
        """
        if self.state is not SessionState.SUSPENDED or self.player is None:
            return
        if self._has_exited():
            return
        if self.is_slideshow_paused():
            xbmc.executebuiltin("Action(Play)")
        self.state = SessionState.PLAYING
        resumed = self.position
        self.player.resume_at(resumed)
        messages.log(
            "BGM resume: track={0} (was {1})".format(
                resume_offset(resumed), _track_label(resumed)
            )
        )

    def _has_exited(self) -> bool:
        """Whether the slideshow this session belongs to is over (FR-004).

        Returns:
            True once the slideshow window has closed, Kodi has asked the
            addon to abort, or teardown has already run -- the three ways
            data-model.md reaches ``TERMINATED``.
        """
        return (
            self.state is SessionState.TERMINATED
            or not self.is_slideshow_active()
            or bool(self.monitor.abortRequested())
        )

    def _wait(self) -> None:
        """Block until the slideshow closes or Kodi asks the addon to abort.

        Uses the abort-aware ``Monitor.waitForAbort``, never a raw sleep
        (constitution principle 1.1, D-002).
        """
        while self.is_slideshow_active() and not self.monitor.abortRequested():
            if self.monitor.waitForAbort(WAIT_INTERVAL_SECONDS):
                break
        if self.monitor.abortRequested():
            self.end_reason = REASON_ABORT_REQUESTED

    def _teardown(self) -> None:
        """Take any state to ``TERMINATED`` (FR-004, FR-013, FR-016, D-003).

        Fade out, wait the ramp out, stop the player, abandon anything still
        in flight, restore the user's volume, and log ``session end`` with the
        level it was restored to -- the evidence for D-003's invariant.
        """
        if self.state is SessionState.PLAYING:
            # FR-016: the level last observed while BGM was audible wins over
            # whatever was captured at session start. effective_baseline (not
            # capture_baseline) so a teardown racing the initial fade-in
            # re-baselines onto that ramp's target, not a mid-ramp sample.
            self.baseline_volume = fader.effective_baseline()
        baseline = self.baseline_volume
        try:
            if self.state is SessionState.PLAYING and baseline is not None:
                fader.fade(Direction.OUT, baseline)
                fader.join(FADE_JOIN_TIMEOUT_SECONDS)
        finally:
            self._finish(baseline)

    def _finish(self, baseline: Optional[int]) -> None:
        """Silence everything this session started, whatever else went wrong.

        Nested inside teardown's ``finally`` so the order of the two
        guarantees is explicit: BGM must not outlive the slideshow (FR-004),
        but even a failure doing that must not leave the user's volume
        attenuated (D-003) or ``session end`` unlogged.

        Args:
            baseline: Volume to restore, or None for a session that never
                made a sound -- nothing was altered, so nothing is written.
        """
        try:
            self._stop_player()
        finally:
            fader.cancel()
            if baseline is None:
                restored = fader.capture_baseline()
            else:
                fader.restore(baseline)
                restored = baseline
            self.state = SessionState.TERMINATED
            messages.log(
                "session end: reason={0} volume restored to {1}".format(
                    self.end_reason, restored
                )
            )

    def _stop_player(self) -> None:
        """Stop this session's BGM, if any is actually playing.

        Only ``PLAYING`` owns a stream worth stopping. Playback Kodi was
        already doing when the slideshow started is left alone -- under the
        ``Yield`` policy this session never owned a player, and stopping one
        it does not own would break FR-014 -- and so is a slideshow video
        clip: while ``SUSPENDED`` the single player Kodi exposes *is* that
        clip (D-001), and stopping it would cut the slideshow's own content
        short on the way out (Edge Case 3, FR-004).
        """
        if self.player is not None and self.state is SessionState.PLAYING:
            self.player.stop()


def _reason_of(reason: Optional[Reason]) -> str:
    """Name a failed validation for the log.

    Args:
        reason: The reason ``config.validate`` reported, if any.

    Returns:
        The reason's wire value, falling back to ``EMPTY`` -- a failing
        result always carries a reason, and an unusable source with none
        named is still an unusable source.
    """
    return reason.value if reason is not None else Reason.EMPTY.value
