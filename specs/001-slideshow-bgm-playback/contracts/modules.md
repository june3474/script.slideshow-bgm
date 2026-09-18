# Contract: Internal Module Interfaces

**Consumers**: the modules themselves, and `tests/` — these seams are where the Kodi
fakes ([research.md D-008](../research.md)) are injected, so they are a testing contract
as much as a design one.

Signatures below are the public surface of each module. Everything else is private.
Python 3.8 floor applies: `Optional[X]` / `List[X]` from `typing`, never `X | None` or
builtin generics at runtime. Constitution 6.1 requires annotations and Google-style
docstrings on every one of these; 6.3 caps each at cyclomatic complexity 10.

Entity names (`BgmSource`, `SessionState`, `BgmPosition`, …) are defined in
[data-model.md](../data-model.md).

---

## `resources/lib/__init__.py`

Module-level singletons resolved once at import:

```python
addon: xbmcaddon.Addon
addon_id: str      # "script.slideshow-bgm"
addon_name: str    # "Slideshow-BGM" (resources/language/resource.language.en_gb/strings.po)
profile_dir: str   # special://profile/addon_data/script.slideshow-bgm/ (translated)
```

## `resources/lib/config.py` — FR-005..FR-008, FR-012, FR-014

```python
def read_source() -> Optional[BgmSource]:
    """Read settings and build a BgmSource, or None if unconfigured."""

def validate(source: BgmSource) -> ValidationResult:
    """Run the four ordered checks from contracts/settings.md."""

def existing_playback_policy() -> Policy:
    """TAKE_OVER (default) or YIELD, per FR-014."""
```

`ValidationResult` carries an `ok: bool` plus a `reason` enum
(`NOT_SELECTED` | `MISSING` | `NOT_MUSIC_PLAYLIST` | `EMPTY`, in check order) so the
caller can pick the right message. `NOT_MUSIC_PLAYLIST` (added 2026-09-15, research.md
R-8 addendum) is `.xsp`-only and gets its own error-styled notification rather than the
generic one every other reason shares (`session.py`'s `_disable`).

**Contract**: nothing in this module talks to the user — `read_source` and `validate`
are pure with respect to the UI, which is what makes validation testable without a
display. Choosing what a failure *says* belongs to `session.py`, its only caller.
`prompt_until_valid()` (a settings-time blocking re-selection loop for FR-011) was
removed 2026-09-15: Script Mode gives Kodi no moment at which to call it, so it had no
production call site. See research.md D-010's addendum.

## `resources/lib/playlist.py` — FR-006, FR-008, FR-010, FR-012, D-009, R-8

```python
def resolve(source: BgmSource) -> Optional[str]:
    """Absolute path of the playlist to hand to PlayMedia, or None if unplayable."""

def scan_directory(path: str) -> List[str]:
    """Recursive bytes-walk for the FR-006 extension set, case-insensitive."""

def parse_pls(path: str) -> List[str]:
    """Ordered track paths from a .pls file (R-8). NumberOfEntries is a hint
    only; actual File<N>= entries are trusted. A resolved entry that does not
    exist (xbmcvfs.exists) is dropped."""

def resolve_xsp(path: str) -> List[str]:
    """Ordered track paths from a .xsp smart playlist (R-8), via the same
    Files.GetDirectory JSON-RPC call Kodi's own "Browse into" uses. Never
    raises; empty list + LOGERROR on any JSON-RPC failure."""

def is_music_smartplaylist(path: str) -> bool:
    """Whether a .xsp's root <smartplaylist type="..."> is songs/music (R-8,
    added 2026-09-15). Reads the XML directly, never via JSON-RPC. Fails
    closed (False) for any other type or an unreadable/malformed file, and
    self-logs the specific reason (LOGWARNING for a wrong type, LOGERROR for
    unreadable/malformed/wrong root) -- config.py only ever sees the coarse
    bool."""

def write_m3u(tracks: List[str], destination: str) -> bool:
    """False on a failed or partial write, which leaves any existing
    destination untouched -- content and mtime alike (D-009)."""

```

`needs_regeneration` was removed 2026-09-15 along with the mtime cache it served: every
derived source is now re-resolved on each `resolve()` call, and `_regenerate` skips the
file write when the resolved track list is unchanged. See D-009's third addendum for the
measurements behind that.

**Contract**: `scan_directory` walks **bytes** paths and decodes explicitly; it must
never let a non-ASCII filename raise `UnicodeError`. Existence checks use
`xbmcvfs.exists`, never `os.path.exists` -- `scan_directory` for the files it walks,
and `parse_pls` for each `File<N>=` entry it resolves.

**R-8 (added 2026-09-14)**: real-device testing found Kodi's own `PlayMedia`
`playoffset` never advances past track 1 for `.pls`/`.xsp` sources. `resolve()` now
derives the same `bgm.m3u` a `DIRECTORY` source already used for these two formats too
(via `parse_pls`/`resolve_xsp`), so `player.py`'s resume mechanism only ever sees a
plain, working `.m3u` regardless of the source's original format. A plain `.m3u`
playlist source is unaffected -- it is still handed to `PlayMedia` exactly as chosen.
`shuffle`/`supports_shuffle` are unaffected too: both stay computed from the *original*
source path's extension (see `BgmSource` in data-model.md), so FR-008's "own native
order" policy for `.pls`/`.xsp` is unchanged.

## `resources/lib/player.py` — FR-001..FR-003, D-001, D-004, D-005, D-006

```python
class BgmPlayer(xbmc.Player):
    def start(self, playlist: str, shuffle: bool) -> None:
        """Prime shuffle/repeat, PlayMedia, fade in (FR-001)."""

    def resume_at(self, position: BgmPosition) -> None:
        """Replay at the track following position.track_index, fade in (FR-003)."""

    def stop_bgm(self) -> None:
        """Fade out, then stop (D-003). Every transition fades, so there is no
        non-fading variant."""

    def onAVStarted(self) -> None:
        """Record track_index from Playlist.Position(music) (D-005), and
        track_count from Playlist.Length(music) (T041, added 2026-09-14) --
        a failed length read does not invalidate an otherwise-successful
        position read, it just leaves track_count at 0 (unknown)."""

    def onPlayBackStopped(self) -> None: ...
    def onPlayBackEnded(self) -> None: ...
```

**Contracts**:

- `onPlayBackStopped` and `onPlayBackEnded` are indistinguishable in effect and MUST
  share one handler — Kodi fires either one when a video clip claims the player.
- Callbacks arrive on Kodi's thread. They MUST NOT block; anything slow is handed to the
  session thread. **One exception**: `fader`'s snap to 0 runs inline — see the fader
  contract below for why deferring it loses the R-6 race.
- `resume_at` targets `resume_offset(position)` for every source — no seek, no
  per-format branch (D-004; R-8 moved the one necessary per-format step to
  `playlist.py`'s `resolve()`, one layer earlier, so this module still never branches on
  format). `resume_offset` is `track_index + 1`, wrapped to `1` when that would exceed
  `track_count` (real Kodi clamps an out-of-range `playoffset` to the last track rather
  than wrapping it itself — T041 finding, research.md D-006's addendum). Falls back to
  the unwrapped `track_index + 1` when `track_count` is unknown (`0`). An invalid index
  falls back to `playoffset=1` (track 1 under `playoffset`'s own 1-indexed convention —
  research.md D-006's 2026-09-18 addendum).
- Callbacks fire for the **slideshow's own video clips** too. Every handler must first
  establish whether the event concerns BGM or a slide, via `Slideshow.IsVideo`.

## `resources/lib/fader.py` — FR-013, D-003

```python
def capture_baseline() -> int:
    """Current global volume, 0-100. Read via JSON-RPC Application.GetProperties.

    Called at session start, and again at each PLAYING -> SUSPENDED transition and
    before an end-of-session fade-out from PLAYING (FR-016), so it always reflects the
    volume last observed while BGM was audible rather than a value frozen at session
    start.
    """

def fade(direction: Direction, baseline: int, duration_ms: int = 1000) -> None:
    """Ramp global volume via the SetVolume builtin (D-013), never JSON-RPC.

    Every step calls xbmc.executebuiltin(f"SetVolume({percent})") with no second
    argument, so Kodi's volume OSD is never triggered (D-013) — JSON-RPC's
    Application.SetVolume shows it unconditionally with no way to suppress it.

    IN  sets the volume to 0 synchronously, then ramps to baseline.
    OUT ramps from the current volume to 0.
    """

def restore(baseline: int) -> None:
    """Set volume back to the captured baseline via the SetVolume builtin (D-013).
    Idempotent, never raises. Claims a new generation and writes in the same
    critical section, so it is the last word — callers need not cancel() first."""

def cancel() -> None:
    """Abandon any ramp in flight without waiting for it."""

def join(timeout: Optional[float] = None) -> bool:
    """Wait for every ramp still running, on one overall timeout budget.
    Does NOT invalidate anything — session teardown calls fade(OUT) then join()
    to let that ramp finish audibly (SC-003). Pair it with cancel() to abandon."""
```

**Why `IN` snaps to 0 first**: every fade-in begins from `baseline`, not from silence —
the previous fade-in left it there. A ramp that started from the *current* volume would
be a no-op sitting at full volume for a second, which is the failure mode this contract
exists to prevent. There is deliberately no `from_volume` parameter: `IN` always starts
at 0 and ends at `baseline`, `OUT` always ends at 0.

**Threading (risk R-6)**: the snap to 0 MUST run inline on the calling thread, before any
worker is spawned for the ramp. At a clip's start it is racing the clip's audio becoming
audible, and thread-startup latency loses that race. The snap is one `SetVolume` builtin
call with no I/O, so it is safe to run on a Kodi callback thread; only the ramp is deferred.

**Invariant (D-003)**: `restore()` runs in a `finally` on every exit path. A crash mid-fade
must not leave the user's volume attenuated. `restore` swallowing its own errors is
deliberate — it is the last thing to run and must not mask the original exception.

**Concurrency (D-003's 2026-09-15 addendum)**: a module-level generation counter, not the
cancellation `Event`, is what decides who may write. Every transition — `fade`, `cancel`,
`restore` — claims a new generation under `_lock`, and a ramp step re-checks its own
generation **inside the same critical section as its write**, so a step already past its
cancellation check can never land after the transition that superseded it. The `Event`
survives only as a latency optimization (it wakes a sleeping step instead of letting it
sleep out its interval). Lock discipline: inside the lock, only a generation check, a
state change and a single `SetVolume` call; `capture_baseline()` (JSON-RPC),
`Thread.join()` and `Event.wait()` always run outside it.

**Re-baselining (FR-016, resolves R-2's correctness half)**: the caller (`player.py` at a clip start,
`session.py` at teardown) MUST call `capture_baseline()` again — and use the fresh value
as `baseline` from that point on — before snapping volume to 0. Without this, a deliberate
volume change the user makes while BGM is playing is silently discarded at the next fade
or at the final `restore()`.

## `resources/lib/session.py` — FR-004, D-002

```python
class SlideshowSession:
    def run(self) -> None:
        """Own the whole lifecycle: start, Monitor wait loop, teardown."""

    def is_slideshow_active(self) -> bool:
        """xbmc.getCondVisibility('Slideshow.IsActive')."""
```

**Contracts**:

- The wait loop is `Monitor.waitForAbort(0.5)` — abort-aware, never `xbmc.sleep()`
  (D-002). The interval is fixed by SC-003's budget and must not be shortened.
- Teardown runs on every exit path: cancel fades, stop the player, join daemon threads,
  `fader.restore()`, log `session end`.
- All threads are daemons (principle 2.1) and are joined with a timeout — a hung fade
  must not prevent process exit (FR-004).

## `resources/lib/skinconnector.py` — D-007

```python
def find_slideshow_xml() -> List[str]: ...
def is_hooked(path: str) -> bool: ...
def install(path: str) -> bool: ...
def uninstall(path: str) -> bool: ...
```

Full semantics in [skin-integration.md](./skin-integration.md).

## `resources/lib/messages.py` — FR-009, FR-012, D-010

```python
def log(message: str, level: int = xbmc.LOGINFO) -> None:
    """Emit '[slideshow-BGM] ' + message. The only xbmc.log call site."""

def notify(message: str, icon: str = xbmcgui.NOTIFICATION_INFO) -> None:
    """Non-blocking toast (FR-012). Heading is always addon_name ("Slideshow-BGM").
    icon (added 2026-09-15) lets a specific failure (e.g. Reason.NOT_MUSIC_PLAYLIST)
    read as an error rather than the routine default."""
```

**Contract**: every user-visible string is looked up from `strings.po` by id. No
hardcoded literals. Line format is fixed by [logging.md](./logging.md).

There is deliberately no blocking-dialog wrapper. `ok()` and `yesno()` existed for
FR-011's settings-time prompt and were removed 2026-09-15 along with their only caller,
`config.prompt_until_valid` — Script Mode reaches no moment at which a blocking dialog
could be raised, so every surface this addon has is non-blocking (research.md D-010's
addendum).

## Entry points

```python
# addon.py  - Script Mode; launched by the skin hook per slideshow
def main() -> None:
    """Build the session and run it. One process per slideshow."""

# service.py - xbmc.service; runs once at profile login, then exits
def main() -> None:
    """Install the skin hook and return. Holds nothing (principle 2.2).

    On failure, shows one non-blocking notification for the run (FR-015) --
    skinconnector already logged the specific reason and remedy per file attempted.
    """
```

---

## Dependency direction

```text
addon.py ──> session ──> player ──> fader
                │           └─────> messages
                ├─────> config ──> playlist ──> messages
                └─────> messages

service.py ──> skinconnector ──> messages
service.py ──> messages   (direct: the FR-015 failure notification)
```

Acyclic and one-directional. `messages` is the only module every other one may import;
it imports nothing from the addon. `fader` never imports `player` — the player asks for
fades, not the reverse. `skinconnector` logs its own detailed failures (reason + remedy);
`service.py` calls `messages.notify()` directly rather than through `skinconnector`,
because the notification is a policy decision about the whole run (one toast regardless
of how many skin files were attempted), not a fact about any single file. Any new edge
that closes a cycle is a design error, not a refactor opportunity.
