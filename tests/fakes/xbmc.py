"""Hand-written fake of the `xbmc` module for pytest (research.md D-008).

Injected into ``sys.modules`` by ``tests/conftest.py`` before any
``resources.lib`` import, so it must win over the real Kodistubs package that
also installs an importable (but inert) ``xbmc`` module for mypy's benefit.

Reconciled against the real-Kodi probe log
(``tests/manual/kodi-probe-run.log``, captured 2026-09-13, Kodi 21.3) rather
than against assumption alone:

- D-001: a slideshow video clip claiming the player fires ``onPlayBackStopped``
  on every live ``Player`` instance -- never ``onPlayBackEnded``, confirmed on
  every clip transition in both the probe's ``.pls`` and ``.xsp`` runs -- and
  the interrupted stream is torn down, not merely displaced:
  ``getTime()``/``getPlayingFile()`` raise ``RuntimeError`` immediately after,
  exactly as real Kodi did.
- D-002: ``Slideshow.IsActive`` / ``IsVideo`` / ``IsPaused`` are settable
  conditions read through ``getCondVisibility``.
- D-003/D-013: one global volume register. Reads go through
  ``executeJSONRPC`` (``Application.GetProperties``); writes go ONLY through
  the ``SetVolume`` builtin, which is recorded together with whether its
  optional ``showVolumeBar`` argument was ever passed (the R-2 regression
  the fader contract exists to prevent).
- D-005: ``Playlist.Position(music)`` is a settable, 1-indexed infolabel
  string that is empty when nothing plays -- the probe confirmed a populated,
  usable index for both ``.pls`` (``pos='1' len='10'``) and ``.xsp``
  (``pos='1' len='7'``).
- D-004/D-006: ``PlayMedia`` and ``PlayerControl`` builtin calls are recorded
  verbatim, with ``PlayMedia``'s ``playoffset`` parsed out, so tests can
  assert what a resume actually targeted.
- ``Files.GetDirectory``: fakes the JSON-RPC call playlist.py's ``.xsp``
  resolver uses. A test configures ``world.xsp_directories[<path>]`` with the
  full ordered list of file entries a directory should "contain"; the fake
  slices it per the caller's requested ``limits`` the same way real Kodi
  paginates, so a test can exercise the resolver's pagination loop just by
  configuring enough entries. Every call's directory/limits are recorded in
  ``world.get_directory_calls``.

Deliberately NOT implemented: ``xbmc.sleep``. Principle 1.1 forbids raw
polling where a Monitor wait exists; production code must never call it, and
leaving it absent turns an accidental call into a loud ``AttributeError``
instead of a silent pass.
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

LOGDEBUG = 0
LOGINFO = 1
LOGWARNING = 2
LOGERROR = 3
LOGFATAL = 4
LOGNONE = 5

_SET_VOLUME_RE = re.compile(r"^SetVolume\((\d+)(?:,\s*([A-Za-z]+))?\)$")
_PLAY_MEDIA_RE = re.compile(r"^PlayMedia\(([^,)]+)(?:,\s*playoffset=(-?\d+))?\)$")


class World:
    """All fake Kodi state. One instance, shared by every fake API surface.

    Tests reach it as ``xbmc.world`` and call :meth:`reset` in a fixture
    (see ``tests/conftest.py``) so state never leaks between tests.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Return every field to its Kodi-idle default."""
        self.players: List["Player"] = []
        self.playing: Optional[str] = None  # None | "audio" | "video"
        self.current_file: str = ""
        self.elapsed: float = 0.0
        self.conditions: Dict[str, bool] = {
            "Slideshow.IsActive": False,
            "Slideshow.IsVideo": False,
            "Slideshow.IsPaused": False,
        }
        self.playlist_position: str = ""
        self.playlist_length: str = ""
        self.volume: int = 100
        self.muted: bool = False
        self.builtins: List[str] = []
        self.volume_calls: List[Tuple[int, bool]] = []
        self.play_media_calls: List[Dict[str, Any]] = []
        self.abort_requested: bool = False
        self.log_lines: List[Tuple[str, int]] = []
        self.xsp_directories: Dict[str, List[Dict[str, Any]]] = {}
        self.get_directory_calls: List[Dict[str, Any]] = []

    # -- Simulated Kodi-side causality (not part of the real xbmc API) -----

    def start_audio(self, path: str) -> None:
        """BGM (or any audio) begins playing, e.g. after a ``PlayMedia`` call."""
        self.playing = "audio"
        self.current_file = path
        self.elapsed = 0.0

    def start_video_clip(self, path: str) -> None:
        """A slideshow video clip claims the player (D-001).

        Matches the probe exactly: whatever was playing gets
        ``onPlayBackStopped`` -- never ``onPlayBackEnded`` -- and the stream
        is gone (``playing`` becomes ``None``, so ``getTime``/
        ``getPlayingFile`` raise) *before* the callback fires, then the video
        becomes current.
        """
        was_playing = self.playing
        self.playing = None
        self.current_file = ""
        if was_playing is not None:
            self.fire_stopped()
        self.playing = "video"
        self.current_file = path

    def end_video_clip(self) -> None:
        """The current video clip finishes; nothing is playing until resumed."""
        self.playing = None
        self.current_file = ""

    def fire_stopped(self) -> None:
        """Dispatch ``onPlayBackStopped`` to every live Player instance."""
        for player in list(self.players):
            player.onPlayBackStopped()

    def fire_ended(self) -> None:
        """Dispatch ``onPlayBackEnded`` -- never observed by the probe for a
        clip interruption, but the player contract requires both callbacks
        to share one handler, so tests must be able to exercise this path
        too."""
        for player in list(self.players):
            player.onPlayBackEnded()

    def fire_av_started(self) -> None:
        """Dispatch ``onAVStarted`` to every live Player instance (D-005)."""
        for player in list(self.players):
            player.onAVStarted()


world = World()


def log(message: str, level: int = LOGINFO) -> None:
    """Record a log line instead of writing to a real kodi.log."""
    world.log_lines.append((message, level))


def sleep(milliseconds: int) -> None:  # pragma: no cover - see module docstring
    """Deliberately absent behavior -- see module docstring."""
    raise AttributeError(
        "xbmc.sleep must never be called (constitution principle 1.1); "
        "use Monitor.waitForAbort instead"
    )


def getCondVisibility(condition: str) -> bool:
    """Fake ``Slideshow.*`` (and any other) boolean condition lookup."""
    return world.conditions.get(condition, False)


def getInfoLabel(label: str) -> str:
    """Fake infolabel lookup -- only the labels this design reads."""
    if label == "Playlist.Position(music)":
        return world.playlist_position
    if label == "Playlist.Length(music)":
        return world.playlist_length
    return ""


def _apply_set_volume(percent: str, show_osd_arg: Optional[str]) -> None:
    volume = int(percent)
    world.volume = volume
    show_osd = show_osd_arg is not None and show_osd_arg.lower() == "showvolumebar"
    world.volume_calls.append((volume, show_osd))


def _apply_play_media(path: str, playoffset: Optional[str]) -> None:
    world.play_media_calls.append(
        {
            "path": path,
            "playoffset": int(playoffset) if playoffset is not None else None,
        }
    )


def executebuiltin(function: str) -> None:
    """Record every builtin call verbatim; apply the ones this design uses.

    ``SetVolume`` and ``PlayMedia`` are parsed into structured records
    (``world.volume_calls`` / ``world.play_media_calls``) because fader.py
    and player.py tests need to assert on percentages, the OSD-suppression
    argument (D-013), and the resume ``playoffset`` (D-004) without
    re-parsing strings themselves. Everything else (``PlayerControl(...)``)
    is only recorded verbatim in ``world.builtins``.
    """
    world.builtins.append(function)
    set_volume_match = _SET_VOLUME_RE.match(function)
    if set_volume_match:
        _apply_set_volume(*set_volume_match.groups())
        return
    play_media_match = _PLAY_MEDIA_RE.match(function)
    if play_media_match:
        _apply_play_media(*play_media_match.groups())


def executeJSONRPC(request: str) -> str:
    """Fake JSON-RPC dispatcher -- only ``Application.GetProperties``.

    That is the only JSON-RPC method this design's read path uses (D-013);
    every volume *write* goes through the ``SetVolume`` builtin above, never
    JSON-RPC.
    """
    parsed = json.loads(request)
    request_id = parsed.get("id", 1)
    method = parsed.get("method")
    if method == "Application.GetProperties":
        properties = parsed.get("params", {}).get("properties", [])
        result = {}
        if "volume" in properties:
            result["volume"] = world.volume
        if "muted" in properties:
            result["muted"] = world.muted
        return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})
    if method == "Files.GetDirectory":
        return _files_get_directory(request_id, parsed.get("params", {}))
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "Method not found (fake)"},
        }
    )


def _files_get_directory(request_id: Any, params: Dict[str, Any]) -> str:
    """Fake ``Files.GetDirectory``, paginated like real Kodi's own result.

    Slices ``world.xsp_directories[directory]`` by the requested ``limits``,
    exactly as real Kodi bounds its SQL result window -- so a test can drive
    the resolver's pagination loop just by configuring enough entries, rather
    than by hand-crafting individual page responses.
    """
    directory = params.get("directory", "")
    limits = params.get("limits", {})
    start = int(limits.get("start", 0))
    items = world.xsp_directories.get(directory, [])
    end = int(limits.get("end", len(items)))
    world.get_directory_calls.append(
        {
            "directory": directory,
            "start": start,
            "end": end,
            "properties": params.get("properties", []),
        }
    )
    actual_end = min(end, len(items))
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "files": items[start:end],
                "limits": {"start": start, "end": actual_end, "total": len(items)},
            },
        }
    )


class Player:
    """Fake of ``xbmc.Player``. Unoverridden callbacks default to no-ops,
    matching the real API, so a subclass need only override what it uses.
    """

    def __init__(self) -> None:
        world.players.append(self)

    def isPlayingAudio(self) -> bool:
        return world.playing == "audio"

    def isPlayingVideo(self) -> bool:
        return world.playing == "video"

    def getTime(self) -> float:
        if world.playing is None:
            raise RuntimeError("Kodi is not playing any media file")
        return world.elapsed

    def getPlayingFile(self) -> str:
        if world.playing is None:
            raise RuntimeError("Kodi is not playing any media file")
        return world.current_file

    def stop(self) -> None:
        """Stop whatever is playing (FR-014's TakeOver policy uses this).

        Matches real Kodi: firing ``onPlayBackStopped`` on every live Player
        instance -- including the caller's own, if already constructed -- and
        leaving nothing playing. A no-op when nothing was playing.
        """
        if world.playing is not None:
            world.playing = None
            world.current_file = ""
            world.fire_stopped()

    def onPlayBackStarted(self) -> None:
        pass

    def onAVStarted(self) -> None:
        pass

    def onAVChange(self) -> None:
        pass

    def onPlayBackEnded(self) -> None:
        pass

    def onPlayBackStopped(self) -> None:
        pass

    def onPlayBackPaused(self) -> None:
        pass

    def onPlayBackResumed(self) -> None:
        pass

    def onPlayBackSeek(self, seekTime: int, seekOffset: int) -> None:
        pass

    def onPlayBackSeekChapter(self, chapter: int) -> None:
        pass

    def onPlayBackSpeedChanged(self, speed: int) -> None:
        pass

    def onPlayBackError(self) -> None:
        pass

    def onQueueNextItem(self) -> None:
        pass


class Monitor:
    """Fake of ``xbmc.Monitor``. ``waitForAbort`` never really sleeps --
    tests drive ``world.abort_requested`` directly instead of paying for a
    real 0.5 s wait per iteration.
    """

    def abortRequested(self) -> bool:
        return world.abort_requested

    def waitForAbort(self, timeout: float) -> bool:
        return world.abort_requested

    def onNotification(self, sender: str, method: str, data: str) -> None:
        pass

    def onSettingsChanged(self) -> None:
        pass
