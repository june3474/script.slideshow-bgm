"""Throwaway probe for script.slideshow-bgm Phase 0 verification.

Logs every Player and Monitor callback with a snapshot of the state the design
depends on, so a single slideshow run turns the open hypotheses in
specs/001-slideshow-bgm-playback/research.md into observations.

Every line is prefixed [BGM-PROBE] for grepping out of kodi.log.

This is a service addon only because a probe needs to be running before the
slideshow starts. That is not an endorsement of the service extension point for
the real addon -- see research.md D-007 for why it was rejected there.
"""
import json
import time

import xbmc

PREFIX = "[BGM-PROBE]"
START = time.time()

# Sampled often enough to catch ordering; the probe logs only on change.
POLL_SECONDS = 0.25


def log(event, detail=""):
    """Emit one probe line: elapsed ms, event name, state snapshot, detail."""
    elapsed = int((time.time() - START) * 1000)
    xbmc.log(
        "%s +%dms %-22s %s %s" % (PREFIX, elapsed, event, snapshot(), detail),
        xbmc.LOGINFO,
    )


def _volume():
    """Global volume and mute state via JSON-RPC, or ('?', '?') on failure."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "Application.GetProperties",
        "params": {"properties": ["volume", "muted"]},
    }
    try:
        result = json.loads(xbmc.executeJSONRPC(json.dumps(request))).get("result", {})
        return result.get("volume", "?"), result.get("muted", "?")
    except (ValueError, TypeError):
        return "?", "?"


def _player_time(player):
    """getTime() guarded -- it raises once nothing is playing, which is the point."""
    try:
        return "%.2f" % player.getTime()
    except Exception as exc:                      # noqa: BLE001 - probe wants the type
        return "ERR(%s)" % type(exc).__name__


def _playing_file(player):
    try:
        return player.getPlayingFile()
    except Exception as exc:                      # noqa: BLE001
        return "ERR(%s)" % type(exc).__name__


def discrete_state():
    """The fields worth logging on change. Deliberately excludes elapsed time."""
    player = xbmc.Player()
    return (
        xbmc.getCondVisibility("Slideshow.IsActive"),
        xbmc.getCondVisibility("Slideshow.IsVideo"),
        xbmc.getCondVisibility("Slideshow.IsPaused"),
        player.isPlayingAudio(),
        player.isPlayingVideo(),
        # The R-5 question: is this populated for .pls / .xsp?
        xbmc.getInfoLabel("Playlist.Position(music)"),
        xbmc.getInfoLabel("Playlist.Length(music)"),
    )


def snapshot():
    """One-line rendering of everything the design depends on."""
    player = xbmc.Player()
    active, is_video, paused, audio, video, pos, length = discrete_state()
    volume, muted = _volume()
    return (
        "ss[active=%d video=%d paused=%d] play[audio=%d video=%d t=%s] "
        "music[pos=%r len=%r] vol=%s muted=%s file=%r"
        % (
            active, is_video, paused,
            audio, video, _player_time(player),
            pos, length,
            volume, muted,
            _playing_file(player),
        )
    )


class ProbePlayer(xbmc.Player):
    """Logs every player callback. Names match the Kodi Python API exactly."""

    def onPlayBackStarted(self):
        log("onPlayBackStarted")

    def onAVStarted(self):
        log("onAVStarted")

    def onAVChange(self):
        log("onAVChange")

    def onPlayBackEnded(self):
        log("onPlayBackEnded")

    def onPlayBackStopped(self):
        log("onPlayBackStopped")

    def onPlayBackPaused(self):
        log("onPlayBackPaused")

    def onPlayBackResumed(self):
        log("onPlayBackResumed")

    def onPlayBackSeek(self, seek_time, seek_offset):
        log("onPlayBackSeek", "time=%s offset=%s" % (seek_time, seek_offset))

    def onPlayBackSeekChapter(self, chapter):
        log("onPlayBackSeekChapter", "chapter=%s" % chapter)

    def onPlayBackSpeedChanged(self, speed):
        log("onPlayBackSpeedChanged", "speed=%s" % speed)

    def onPlayBackError(self):
        log("onPlayBackError")

    def onQueueNextItem(self):
        log("onQueueNextItem")


class ProbeMonitor(xbmc.Monitor):
    """Logs every notification -- used to confirm none fire for the slideshow window."""

    def onNotification(self, sender, method, data):
        log("onNotification", "sender=%s method=%s data=%s" % (sender, method, data))

    def onSettingsChanged(self):
        log("onSettingsChanged")


def main():
    monitor = ProbeMonitor()
    player = ProbePlayer()                        # must stay referenced or it is GC'd
    log("PROBE START", "kodi=%s" % xbmc.getInfoLabel("System.BuildVersion"))

    last = None
    while not monitor.abortRequested():
        current = discrete_state()
        if current != last:
            log("state-change", "was=%r" % (last,))
            last = current
        if monitor.waitForAbort(POLL_SECONDS):
            break

    log("PROBE STOP")
    del player


if __name__ == "__main__":
    main()
