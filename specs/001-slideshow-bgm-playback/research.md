# Phase 0 Research: Slideshow Background Music Playback

**Branch**: `001-slideshow-bgm-playback` | **Created**: 2026-09-09 | **Last revised**: 2026-09-11 | **Spec**: [spec.md](./spec.md)

## Evidence base

This addon is built from scratch. No existing implementation is carried forward, and no
prior codebase is treated as a source of truth. Every decision below rests on one of
three things, and each is labelled so the difference stays visible:

| Basis | Meaning |
|---|---|
| **API fact** | Follows from the shape of the Kodi Python API itself — e.g. a method that does not exist cannot be called |
| **Inference** | A reasoned consequence of an API fact, not directly observed |
| **Hypothesis** | Plausible, load-bearing, and **not yet confirmed** — must be verified in a running Kodi |

Per the constitution's Development Workflow, every decision touching Monitor/Player
callback semantics MUST be verified against a running Kodi before merge. A **Hypothesis**
blocks merge when the design would be *wrong* if it failed; where the design is merely
belt-and-braces against it, the confidence line says so explicitly. Verification steps
live in [quickstart.md](./quickstart.md) Tier 2.

---

## D-001: Kodi exposes one shared player, so a video clip ends BGM playback

**Decision**: Model "BGM pause" as *stop → remember where we were → replay*, not as
`Player.pause()` / `Player.resume()`.

**Rationale**:

- **API fact**: `xbmc.Player` represents *the* player. The Python API offers no way to
  instantiate a second, independent audio player alongside it, and no per-player
  addressing on any of its methods.
- **Inference**: when a slideshow's video clip claims that one player, the BGM stream
  cannot survive alongside it. The addon learns about this after the fact, through
  `onPlayBackStopped` / `onPlayBackEnded` — by which point there is no stream left to
  pause or resume.

**Consequence for the spec**: FR-002/FR-003 and the **BGM Pause** entity are written in
user-facing terms — music stops for the clip, comes back after. That observable behavior
is unchanged; the mechanism underneath is stop-and-replay. The data model names the real
states.

**Alternatives considered**:

- `Player.pause()` when a clip starts — rejected: nothing is left to pause by the time
  the addon is notified.
- A second concurrent audio player — rejected: the API exposes no such thing.

**Confidence**: High on the single-player constraint (API fact). **Confirmed by probe**
(2026-09-13, `tests/manual/kodi-probe-run.log`, scenario in
[tools/kodi-probe/README.md](../../tools/kodi-probe/README.md)): the callback is
`onPlayBackStopped` — `onPlayBackEnded` never fired for an interrupted BGM track, across
every clip transition in both the `.pls` and `.xsp` scenario passes. The stream is torn
down, not displaced: every `getTime()`/`getPlayingFile()` call made immediately after the
callback raises `RuntimeError("Kodi is not playing any media file")`.

---

## D-002: Slideshow lifecycle is sampled from boolean conditions, not events

**Decision**: Detect slideshow liveness with
`xbmc.getCondVisibility('Slideshow.IsActive')`, sampled from an
`xbmc.Monitor().waitForAbort(0.5)` loop. Use `Slideshow.IsVideo` to tell whether the
current slide is a video clip.

**Rationale**: Slideshow start and end are Kodi *window* transitions
(`WINDOW_SLIDESHOW`). Kodi's JSON-RPC notification set covers player, application,
system and library events — it does not announce this window opening or closing, so
`Monitor.onNotification` never fires for it and there is nothing to subscribe to.

Constitution principle 1.2 anticipates exactly this case: it permits the Monitor's own
wait loop where Kodi offers no event-driven alternative, and requires "the longest wait
interval that keeps behavior responsive."

**Interval choice — 0.5 s**: SC-003 gives BGM 2 seconds to stop after the slideshow ends
(relaxed from 1 s on 2026-09-11, precisely because the fade alone consumes 1 s). Detection
latency is bounded by the wait interval, so the worst case is interval + 1 s fade. At
0.5 s that is 1.5 s, leaving 0.5 s of headroom; at 1.0 s it is exactly 2.0 s, leaving
none. 0.5 s is therefore the longest interval that keeps any margin.

`Monitor.waitForAbort(0.5)` is used rather than `xbmc.sleep()` because it returns early
on a Kodi shutdown request, which is what FR-004's "terminate together with the
slideshow" and principle 2.1's explicit-cleanup rule require.

**Alternatives considered**:

- `Monitor.onNotification` for slideshow end — rejected: no such notification exists.
- `xbmc.sleep()` — rejected: not abort-aware; principle 1.1 forbids raw polling where a
  Monitor wait is available.

**Confidence**: High on the mechanism. **Confirmed by probe** (2026-09-13,
`tests/manual/kodi-probe-run.log`; resolves R-4): `Slideshow.IsActive` and
`Slideshow.IsVideo` flip correctly and promptly on the sampling loop for every window
open/close and every image/video slide transition, across both scenario passes on Kodi
21.3. No `Monitor.onNotification` ever fired for the slideshow window itself, confirming
there was nothing to subscribe to.

**Caveat found during the probe**: `Slideshow.IsPaused` is not exclusively a user-pause
signal — it read `True` for the entire duration a video clip was the current slide (from
the loading dialog through playback), even though the user never paused anything. A
future code path that wants to detect a genuine user-initiated pause cannot rely on this
condition alone; it would need to be combined with `IsVideo` to disambiguate. Nothing in
this design currently reads `IsPaused`, so this is not a merge blocker — recorded here so
it isn't assumed away later.

---

## D-003: Fades apply to all four transitions, but not all to background music

**Decision** (user-confirmed 2026-09-10, superseding the 2026-09-09 decision; now
FR-013): apply a 1-second fade at all four transitions.

| Transition | What fades | Mechanism |
|---|---|---|
| BGM starts at slideshow start | BGM in | Ramp global volume 0 → baseline |
| A video clip starts | **The clip's audio in** | Drop global volume to 0, ramp to baseline |
| A video clip ends, BGM resumes | BGM in | Ramp global volume 0 → baseline |
| BGM stops at slideshow end | BGM out | Ramp global volume baseline → 0 |

**Rationale**: two API facts constrain what is achievable, and together they explain why
the second row fades something different from the others.

1. Kodi's Python API exposes **no per-player volume**. The `xbmc.Player` method set
   (`play`, `pause`, `stop`, `seekTime`, `getTime`, `isPlayingVideo`, `isPlayingAudio`,
   `getPlayingFile`, …) contains no volume control at all. Volume is a single global
   register, read via the JSON-RPC `Application` namespace and set via the `SetVolume`
   builtin (mechanism finalized in D-013). Every fade is therefore a fade of *whatever
   is currently audible*.
2. Per D-001, when a clip claims the player the BGM stream is already gone by the time
   the addon is notified. There is no background music left to fade out at that moment.

Combining the two: at a clip's start the only thing global volume can act on is **the
clip's own audio**. So the fade there is a fade-*in* of the clip, not a fade-out of the
music. That is the honest reading of "fade on all four transitions" — the user's intent
is that no transition cuts abruptly, and this delivers it for all four.

**Explicitly excluded**: fading the clip's audio *out* as the clip ends. Doing so
requires knowing when the clip is about to finish, which means sampling `getTime()` /
`getTotalTime()` on the video — a second sampling loop alongside D-002's, reintroducing
exactly the kind of thread D-004 removes. The user weighed this and declined it
(2026-09-10).

**Implementation**: a fade helper ramps global volume between 0 and a captured baseline
in steps over 1000 ms (setting mechanism finalized in D-013). The baseline is captured
at session start, re-captured as described in D-012, and restored in a `finally` block
on every exit path, so a crash cannot leave the user's volume altered.

**Ordering hazard at a clip's start**: the drop to 0 must land before the clip's audio is
audible, or the user hears a moment of full-volume clip followed by a dip. Whether the
`onPlayBackStopped` / `onAVStarted` callback arrives early enough is a **Hypothesis** —
the probe (D-008) measures it directly. If it does not, this fade has to be dropped and
FR-013 revisited.

**Probe measurement (2026-09-13, `tests/manual/kodi-probe-run.log`, risk R-6)**: latency
from the slide visually switching to a video clip until `onAVStarted` fires, measured
across every clip transition in both scenario passes:

| Transition | Latency |
|---|---|
| First video clip of a slideshow session | ~1.7 s |
| Every later clip transition in the same session (video→video or image→video) | ~0.2–0.4 s |

The ~1.7 s figure is not random: it coincided, in both scenario passes, with a
`CRenderManager::Configure - timeout waiting for configure` warning and an internal
video-reopen retry in Kodi's own log — a renderer cold-start cost paid once per slideshow
session, not a property of any particular clip file (replaying the *same* clip later in
the same session, once the renderer is warm, drops back to ~0.35 s). Tracked as new risk
R-7 below.

Even the steady-state ~0.2–0.4 s is not zero: a fade triggered from the callback still
starts after the clip's own audio device has begun opening, so some sub-second delay
before volume actually reaches 0 is a property of this design, not a bug to chase out.
Whether that residual delay is audible is Tier 2 step 6's call (quickstart.md) — a log
timestamp alone cannot answer that.

**Alternatives considered**:

- Fades only on addon-initiated transitions (the 2026-09-09 decision) — reversed by the
  user: it left the clip's entry abrupt.
- Full crossfade including a clip fade-out — declined: costs a sampler thread.

**Confidence**: High on the mechanism (API fact). Callback timing at clip start (risk R-6)
is now measured rather than hypothesized — see the probe measurement above; the risk is
downgraded from "unknown" to "known and quantified," not closed, since the first clip of
every session pays a distinct renderer cold-start cost (R-7). The volume-OSD side effect
once tracked as risk R-2 is resolved — see D-013.

**Addendum (2026-09-15): cancellation is a generation counter, not the `Event`.**

*The bug.* `fader.py` cancelled a ramp by setting a `threading.Event` that `_ramp`
checked at the top of each step, then wrote the volume as a separate statement. A worker
could clear the check, lose its scheduling slice, and perform its write *after* a newer
`fade()` — or after `restore()` — had already written. Mid-session that is a ≤ 50 ms blip
the next step corrects. At teardown it is not: `session.py`'s `_finish` calls `cancel()`
then `restore(baseline)`, and a step slipping through writes a mid-ramp value afterwards,
leaving the user's global volume permanently attenuated — exactly the invariant this
decision and plan.md's "captured global volume MUST be restored on every exit path" exist
to protect. The reachable path is ordinary, not exotic: exiting a slideshow while a clip's
fade-in runs, where `_teardown` skips both the fade-out and the `join()` because the state
is `SUSPENDED`. Found 2026-09-15 by an adversarial review; the failure was then reproduced
as a red test showing `volume_calls == [(0,…), (70,…), (4,…)]` — a 4 % write landing after
`restore(70)`.

*The fix.* A module-level `_generation` int is claimed under `_lock` by every transition,
and a ramp step re-checks its generation **inside the same critical section as its write**
(`_write_if_current`). Checking outside the lock would just reopen the same window. Five
consequences worth recording, each of which the review of the design surfaced:

- `fade(IN)`'s inline snap to silence is claimed, snapped and given its worker inside one
  critical section. Previously the snap sat unlocked between `cancel()` and
  `_start_worker()`, so a concurrent `OUT` — parked inside its slow JSON-RPC
  `capture_baseline()` — could install itself afterwards and ramp down from a volume
  nobody was at any more. The snap still runs inline on the calling thread: deferring it
  to the worker loses the R-6 race against the clip's audio.
- `OUT` reads its baseline outside the lock (it is JSON-RPC) and then re-validates the
  generation before using it, abandoning the transition if a newer one has been claimed.
- `restore()` claims a generation and writes in the same critical section, which makes it
  the last word and removes the hidden precondition that callers must `cancel()` first.
- `cancel()` and every `fade` share one internal claim helper, so a transition is never
  two separately-locked mutations with a window between them.
- `join()` tracks *every* worker, not just the newest (a superseded ramp is still a live
  thread until it notices — constitution 2.1). It snapshots the list under the lock and
  joins outside it, since a worker needs that same lock for its final check, and it
  spends **one overall deadline** rather than a fresh timeout per thread. It deliberately
  does **not** claim a generation: teardown calls `fade(OUT)` and then `join()` to let
  that ramp finish audibly (SC-003), so invalidating there would silence every fade-out.
  Abandoning is `cancel()`'s job, and the two compose.

The `Event` is kept purely as a latency optimization — it wakes a sleeping step instead of
letting it sleep out its interval — and is no longer load-bearing for correctness.

*Accepted trade-off.* The lock is now held across a Kodi `executebuiltin()` call. It is
held for a single volume write, never a whole ramp, so `effective_baseline()` — called
from Kodi's callback thread on the R-6-sensitive clip-start path — waits at most one call.
If real-device measurement ever shows `executebuiltin()` latency to matter, the answer
would be a single writer thread with a queue; that is explicitly not built on speculation.

---

## D-004: Every source resumes at the following track

> **Amended 2026-09-14 by R-8** (below): the *resume mechanism* described here (always
> the following track, no per-format branch) is still exactly true and unchanged — what
> changed is one step earlier, at *source resolution*. Real-device testing found Kodi's
> own `playoffset` never advances past track 1 for `.pls`/`.xsp`, so `playlist.py` now
> derives a concrete `bgm.m3u` for those two formats too (as it already did for
> `DIRECTORY`) before this resume path ever runs. See R-8 for the full decision.

**Decision** (user-confirmed 2026-09-10, superseding the 2026-09-09 decision; now
FR-003): when background music resumes after a video clip, it starts at the **beginning
of the track after** the one that was playing. This is uniform across every BGM source —
directory-derived `bgm.m3u`, `.m3u`, `.pls` and `.xsp` alike.

**Rationale**: the alternative was same-track resume at a recorded offset, which forced
three things the addon no longer needs:

- a **1 Hz sampler thread** to record `getTime()` in advance, because `getTime()` is
  unreadable once the stream is gone (D-001);
- a `seekTime()` call with a **verify-and-fall-back** path, since seek reliability varies
  by audio format;
- **per-format branching**, because `.pls` and `.xsp` report a track length of 0 and
  carry no usable position at all.

Dropping to next-track resume removes all three at once. One resume path, no sampler, no
seek, no format branch — and it eliminates the seek-compatibility risk that was the
highest-rated risk in this design (formerly R-1).

**Cost**: the remainder of an interrupted track is skipped. A clip that interrupts at
0:30 of a four-minute track means the last 3:30 are never heard. For background music the
user judged this acceptable (2026-09-10), and it is recorded in the spec as Assumption 6.

**Mechanism**: read the current track index from the `Playlist.Position(music)` infolabel
and resume at `index + 1`. See D-005 for how the index is captured.

**Alternatives considered**:

- Same-track resume at a sampled offset (the 2026-09-09 decision) — reversed by the user
  for the complexity above.
- Same-track-from-zero — rejected: replays audio the user just heard.
- Restarting the whole playlist — rejected: loses position entirely.

**Confidence**: High. This decision removes risk rather than adding it. Its one
dependency — that a track can be targeted at all in a `.pls`/`.xsp` playlist — is
discussed once, in D-005 (risk R-5).

---

## D-005: Track index comes from the playlist infolabel, read in a callback

**Decision**: read the current track index from
`xbmc.getInfoLabel('Playlist.Position(music)')`, evaluated inside `onAVStarted`. No
sampling thread is involved.

**Rationale**: `onAVStarted` fires once when a new item begins playing, which is exactly
when the track index changes — so the index needs no polling at all, satisfying principle
1.1. Reading it from Kodi's own infolabel rather than counting callbacks internally means
the addon never has to reconstruct state Kodi already tracks, and it stays correct if
Kodi reorders or shuffles the playlist underneath.

This reading also answers R-5. If `Playlist.Position(music)` returns a usable index for a
`.pls` / `.xsp` source, then Kodi has **expanded** that playlist file into the music
playlist — and an expanded playlist is one whose tracks can be targeted. The original
worry was targeting, not reading; a valid read is strong evidence targeting works.

**Implementation notes**:

- `getInfoLabel` returns a **string**, and an empty one when nothing is playing. `int()`
  on that raises `ValueError`, so every read needs a guard and a sensible fallback.
- `onAVChange` also exists and fires on any video/audio/subtitle stream change, not only
  on a track change. If verification shows `onAVStarted` misses cases, `onAVChange` can
  supplement it — but only with an explicit "did the index actually change?" guard, or it
  will fire spuriously.

**Alternatives considered**:

- Counting `onAVStarted` events internally to maintain an index — rejected: duplicates
  state Kodi owns and drifts if the playlist changes.
- Polling the infolabel on a timer — rejected: principle 1.1 forbids polling where a
  callback exists.

**Confidence**: High on the approach. **Confirmed by probe** (2026-09-13,
`tests/manual/kodi-probe-run.log`; resolves R-5): `Playlist.Position(music)` is populated
for both `.pls` (`music[pos='1' len='10']` immediately after start) and `.xsp`
(`music[pos='1' len='7']`) — Kodi expands both into the music playlist, and the index is
usable exactly as D-004's resume path needs. One implementation detail the probe
surfaced: the infolabel is **1-indexed** (`pos='1'` for the first track), which the
`index + 1` resume arithmetic must account for.

---

## D-006: Start playback with the `PlayMedia` builtin

**Decision**: Start BGM with `xbmc.executebuiltin('PlayMedia(<playlist>[,
playoffset=N])')` rather than `xbmc.Player.play()`.

**Rationale**: `PlayMedia` is Kodi's general entry point for handing a path or playlist
file to the player, and it accepts a `playoffset` argument naming which item to start
from — which is what D-004's resume path needs. `Player.play()` takes a playlist
object the addon would have to populate itself, which for smart playlists (`.xsp`) means
re-implementing the query Kodi already knows how to run.

**Shuffle and repeat**: `PlayerControl(RandomOn|RandomOff)` and
`PlayerControl(RepeatAll)` only take effect while a player is active, so they cannot be
set before playback begins. The order of operations at session start must therefore
establish playback first and apply the controls immediately after, with the fade-in held
until the controls are in place so the user never hears an unshuffled first moment.
`RepeatAll` implements Assumption 5's loop-back for a track that finishes **naturally**
(the playlist loops rather than ending before the slideshow does); it does **not** cover
the `playoffset`-driven resume boundary case — see the T041 addendum below, where that
turned out to be a separate, wrong assumption.

**Alternatives considered**: `Player.play()` with a hand-built playlist — rejected for
`.xsp`, which FR-007 requires.

**Confidence**: **Hypothesis** on whether `Player.play()` genuinely fails for `.xsp`.
The `playoffset` questions (whether it is 1-indexed, and whether it wraps past the end of
a playlist) are resolved — see the T041 addendum below.

**Addendum (2026-09-14, Tier 2 step 5 / T041 finding)**: real-device testing (a 10-track
`.m3u`/`.pls`/directory source, `PlayMedia(<playlist>,playoffset=N)`) resolved both
open `playoffset` questions:

- **1-indexed, confirmed**: for every in-range `N`, `Playlist.Position(music)` read back
  exactly `N` immediately after resuming — matching `Playlist.Position(music)`'s own
  1-indexed convention (D-005). Also confirmed by reading Kodi's own source
  (`xbmc/interfaces/builtins/PlayerBuiltins.cpp`): `playoffset=N` is parsed as
  `atoi(...) - 1` before being handed to the playlist player, i.e. `N` is 1-indexed on
  the way in.
- **Does not wrap past the end of a playlist — Assumption 5's mechanism was wrong**: at
  the last track (10 of 10), the addon requested `playoffset=11` (`track_index + 1`, per
  D-004's mechanism); `Playlist.Position(music)` read back `10`, not `1`, and stayed `10`
  for every subsequent clip in the session — Kodi clamps an out-of-range `playoffset` to
  the last track rather than wrapping it. `PlayerControl(RepeatAll)` (set once at
  session start) does not reach this case: it only wraps a track that finishes playing
  *naturally*, not an explicit out-of-range `playoffset` argument.

**Fix**: the addon now computes the wrap itself. `Playlist.Length(media)` is Kodi's own
infolabel pairing with `Playlist.Position(media)` (confirmed via `GUIInfoManager.cpp`:
"returns the total size of the current playlist"). `BgmPlayer.onAVStarted`
(`resources/lib/player.py`) now reads it alongside the position into a new
`BgmPosition.track_count` field, and `resume_offset()` wraps to `1` when
`track_index + 1` would exceed it. When the length read is itself unreadable,
`resume_offset()` falls back to the old unwrapped `track_index + 1` — a deliberate
no-regression choice, since Kodi already clamps at the boundary regardless, so nothing is
made worse by not wrapping in that corner case. `.pls` and directory sources use the
identical `.m3u`-shaped playlist mechanism, so this fix covers them uniformly, per D-004.
`.xsp` is a separate, still-open issue — see the T041 addendum below.

---

## D-007: Launch mechanism — a skin `SlideShow.xml` hook, installed once at login

**Decision** (now FR-015): inject
`<onload condition="System.HasAddon(script.slideshow-bgm) +
System.AddonIsEnabled(script.slideshow-bgm)">RunAddon(script.slideshow-bgm)</onload>`
into the active skin's `SlideShow.xml`, installed by a run-once script registered at the
`xbmc.service` extension point which exits immediately after hooking up.

**Rationale**: a Script Mode addon cannot launch itself — something has to tell Kodi to
run it when the slideshow window opens. The hookup also cannot be done by the Script Mode
entry point, because without the hook that entry point never runs and so could never
bootstrap. That leaves Kodi startup / profile login (the service extension point) or an
explicit user action, and only the former satisfies FR-001's "automatically."

**Constitution note**: principle 2.2 forbids "a persistent background service outside
Script Mode." This script is not persistent — it inserts the tag and exits, holding no
threads, timers, or listeners. It is recorded in the plan's Complexity Tracking as a
justified deviation, since it does register at the service extension point.

**Also required**: back up the skin file before editing, check write permission first,
and re-hook when the user changes skins — all now required by FR-015.

### Why not a service addon — the decision record

*This subsection is written to stand on its own so it can be lifted into the project
README. It is the canonical rationale; plan.md's Complexity Tracking points here.*

The obvious way to avoid touching a skin's files is to make this a **service** addon
instead of a Script Mode one: a service starts with Kodi, runs continuously, and could
watch for a slideshow itself. That option was considered and **rejected on 2026-09-10**.

The reason is that Kodi emits no event when the slideshow window opens (D-002). A Script
Mode addon does not need one — the skin hook *is* the event, so the addon is launched at
the instant the slideshow starts and does no work at any other time. A service has no
such trigger available, so it would have to **poll for slideshow start continuously, for
the entire Kodi session**, whether or not the user ever opens a slideshow. The cost is
paid by every user, all the time, to serve a feature used occasionally.

That also strains a stated success criterion. SC-001 gives the addon **2 seconds** from
slideshow start to music at full volume — playback startup plus the 1-second fade-in
(relaxed from an original 1-second budget on 2026-09-11; see spec.md Clarifications).
With the skin hook the detection latency is effectively zero, so the budget is spent
entirely on startup and fade. A polling service adds its poll interval on top of both,
eating into the ~1 second of headroom the relaxed budget leaves — a short-enough interval
(e.g. the same 0.5 s already used for session-liveness sampling, D-002) could still fit,
so timing alone no longer rules a service out. The independent reasons below —
continuous polling cost and the constitution conflict — are what still make it a firm
rejection.

It conflicts with the project constitution as well. Principle 2.2 forbids "a persistent
background service outside Script Mode" and 2.1 forbids any thread or listener outliving
the script's lifecycle, both for the same reason: a Script Mode addon that is launched
and torn down per slideshow cannot degrade the rest of the Kodi session. Adopting a
service would require amending both, a MAJOR constitution change.

The skin hook is not free either, and the trade is worth stating plainly:

| | Skin hook (chosen) | Service addon (rejected) |
|---|---|---|
| Cost when no slideshow is running | None — the addon is not running | Continuous polling for the whole session |
| Slideshow-start latency | ~0; SC-001 met with headroom to spare | Poll interval + fade; SC-001 technically reachable, headroom-constrained |
| Constitution | Compatible (one narrow deviation, see plan.md) | Requires amending principles 2.1 and 2.2 |
| Footprint | Edits one file in the active skin | Touches no skin file |
| Failure mode | A skin update can drop the hook (risk R-3), repaired at next login | None of this class |

The decision comes down to **a one-time, backed-up, reversible edit to one skin file
versus a permanent background cost to the user's entire Kodi session**. The addon writes
a `.original` backup before its first edit, its injected element is guarded by a
condition that makes it inert if the addon is removed, and the change is undone by
uninstalling. Given that, the one-time edit is the smaller imposition.

**Alternatives considered**:

- A **service addon** polling for slideshow start — rejected; see the decision record
  above.
- **`xbmcgui.Window(WINDOW_SLIDESHOW)` with an `onInit`/`onFocus` override** (considered
  2026-09-11) — rejected as technically impossible, not just undesirable. `WINDOW_SLIDESHOW`
  (id 2007) is a native `CGUIWindowSlideShow`, not a Python-created window. Attaching to it
  by id goes through `ProxyExistingWindowInterceptor` in Kodi's own `Window.cpp`, whose
  constructor comment states plainly: *"It is not possible to capture key presses or button
  presses."* That proxy is never registered as the window manager's dispatch target, so
  `onInit`/`onFocus`/`onAction`/`onClick` overrides on it never fire — those callbacks only
  fire for a window Python itself constructs and shows via `WindowXML`. Even if they did
  fire, this would not solve the actual problem: constructing `xbmcgui.Window` at all
  requires Python to already be running, which is precisely the bootstrap gap this decision
  exists to close. (This is unrelated to `xbmc.Player` callbacks, which use a separate
  system-wide dispatcher unaffected by this finding — D-001/D-004/D-005 are untouched.)
- A settings-screen action button as the only mechanism — rejected: a skin change then
  silently breaks the addon with no feedback.
- Asking users to hand-edit `SlideShow.xml` — rejected: unacceptable for an addon
  distributed through the Kodi repository.

**Confidence**: High on the necessity of the mechanism. **Hypothesis** on the exact
`SlideShow.xml` location and structure across skins, and on whether `<onload>` under the
root `<window>` is honored by all of them.

---

## D-008: Testing without Kodi — hand-written fakes for pytest, Kodistubs for mypy

**Decision**: two complementary dev-only dependencies.

- **Kodistubs** (`romanvm/Kodistubs`) satisfies `mypy --strict` — it ships PEP-484
  annotations for the whole Kodi Python API.
- **Hand-written in-repo fakes** (`tests/fakes/`) injected into `sys.modules` before
  import satisfy pytest — Kodistubs' own documentation is explicit that "Kodistubs are
  literally stubs and do not include any useful code," so they cannot drive behavioral
  tests.

**Rationale**: `xbmc` / `xbmcgui` / `xbmcvfs` / `xbmcaddon` are C++ bindings that cannot
be pip-installed into a virtualenv, so they must be substituted. The constitution makes
TDD non-negotiable and requires test tasks for every user story, so the fakes must be
behavioral enough to model the decisions above: a single player that ends audio playback
when a video starts (D-001), settable `Slideshow.*` conditions (D-002), a global volume
register (D-003), and a settable `Playlist.Position(music)` infolabel that returns an
empty string when nothing is playing (D-005).

**Caveat**: the fakes encode what this research *believes* Kodi does. Where a decision is
marked **Hypothesis**, a green test proves only internal consistency, not correct
behavior against Kodi. That is what makes quickstart.md's Tier 2 mandatory rather than
advisory.

**Not unit-testable** (verified manually in Kodi, per the constitution's Development
Workflow): `resources/settings.xml` rendering, dialog appearance, and whether a volume
OSD surfaces during a fade. Callback ordering and infolabel behavior are *not* in this
list — the probe below captures both into a log this session can read directly.

### The probe

Before any implementation code, the throwaway addon in `tools/kodi-probe/` logs Kodi's
real behavior to `~/.kodi/temp/kodi.log`, which can be read back directly. One run turns
D-001, D-002, D-003's clip-start timing, D-005 and risks R-4, R-5 and R-6 from hypotheses
into observations, and the fakes are then built to match the log rather than the
assumption. The scenario to run and the fields it captures are documented once, in
[`tools/kodi-probe/README.md`](../../tools/kodi-probe/README.md).

**Confidence**: High.

---

## D-009: Directory scan and derived-playlist caching

**Decision**: recursively scan with `os.walk()` over a **bytes** path, matching the
FR-006 extension set (`.mp3`, `.wav`, `.ogg`, `.wma`, `.flac`, `.aac`, `.m4a`)
case-insensitively, and write `bgm.m3u` into the addon profile directory. Regenerate only
when `bgm.m3u` is missing or older than `settings.xml`.

**Rationale**: Kodi's `filesystemencoding` has defaulted to ASCII since v19.3, so
non-ASCII filenames can raise `UnicodeError` when handled as `str`. Walking as bytes and
decoding explicitly avoids depending on that default. For the same reason, existence and
stat checks go through `xbmcvfs.exists()` / `xbmcvfs.Stat()` rather than `os.path.*`,
which also lets the addon handle Kodi's `special://` paths.

The mtime comparison delivers SC-004 ("takes effect the next time they start a
slideshow") without rescanning the directory on every launch.

**Confidence**: High on the caching rule. **Hypothesis** on the severity of the encoding
problem on current Kodi versions — but the bytes walk is correct whether or not the
problem bites, so this is one of the hypotheses that does not block merge. The non-ASCII
case must still appear in the tests.

**Addendum, found 2026-09-13 via Tier 2 manual testing (T038 prep)**: `xbmcvfs.exists()`
and `xbmcvfs.listdir()` only recognize a **directory** as existing when its path ends
with a trailing slash — a file's does not need one, and adding one to a file path breaks
it. This is documented, real Kodi VFS behavior (confirmed against a
[Kodi forum thread](https://forum.kodi.tv/showthread.php?tid=337009): *"xbmcvfs.exists(path)
fails if path is a directory not ending in / or \\"*), not something either the spec or
the original test fakes anticipated — the fakes wrapped real `os.path.exists`, which
doesn't care about trailing slashes either way, so 310 passing automated tests gave no
signal. It surfaced only when the user tried Tier 2 step 2 on real Kodi and
`skinconnector.find_slideshow_xml()` failed to descend into a skin's resolution
subdirectory (`1080i/SlideShow.xml` never found, because `os.path.join(parent, name)`
never adds the trailing slash `_find_below`'s recursion needs). The same bug independently
broke `config.validate()` for every `DIRECTORY` source. Both are fixed (normalize to a
trailing slash before any `xbmcvfs.exists`/`listdir` call on a path known to be a
directory), and `tests/fakes/xbmcvfs.py`'s `exists()` now reproduces the quirk so a
regression fails locally instead of only on real Kodi. Worth remembering for any *future*
code that calls `xbmcvfs.exists`/`listdir` on a directory: always via a helper that
guarantees the trailing slash, never a bare `os.path.join`.

**Second addendum, found 2026-09-13, same Tier 2 session — more serious**: real Kodi's
`xbmcvfs.File.write()` and `xbmcvfs.copy()` do **not** reliably raise on a permission
failure; `write()` in particular is documented to return `False` instead (confirmed
against [Kodi's own dev docs](https://xbmc.github.io/docs.kodi.tv/master/kodi-dev-kit/group__python__xbmcvfs.html)).
`skinconnector.py`'s `_write()` and `_back_up()` only ever checked for a raised
exception, never the boolean return — so on a genuinely read-only skin (Estuary,
package-installed under `/usr/share/kodi/`, the single most common real-world case this
whole feature exists to handle) the addon logged `skin hook: installed` at `LOGINFO`
and returned success, while **nothing was actually written**: confirmed live —
`grep -c RunAddon(...) SlideShow.xml` was `0` and the file's mtime was untouched from
its package-install date. Worse, `_is_writable()`'s precondition probe never called
`write()` at all — it only opened and closed a handle — so it could not have caught this
failure mode even in principle, on any backend where opening itself doesn't fail.

All three are fixed: `_is_writable()` now performs a real (empty, harmless) write and
checks its return value for both the file and the directory probe; `_write()` and
`_back_up()` check `write()`/`copy()`'s return value and treat `False` as failure,
never just absence-of-exception as success. `tests/fakes/xbmcvfs.py`'s `File` class now
swallows a failed `open()` for `"w"`/`"a"` modes (matching the confirmed real behavior)
instead of raising, so this exact "reports success, writes nothing" shape is caught by
`pytest`, not only by a live user on a read-only skin. Read-mode (`"r"`) failure
behavior was deliberately left unchanged — there is no equivalent confirmed evidence for
`read()`, and guessing there would just be a different unverified assumption.

**The general lesson, now twice-confirmed**: Kodi's `xbmcvfs` module mixes two failure
conventions across its own surface — some calls raise, some return a falsy value on
failure — and neither this project's design docs nor the original hand-written fakes
assumed that inconsistency going in. Any new `xbmcvfs` call this addon adds should be
verified against Kodi's own dev-kit docs (not assumed to behave like `os`/`shutil`)
before being trusted to fail loudly.

**Third addendum (2026-09-15): the mtime cache is removed — every derived `bgm.m3u` is
now rebuilt on every slideshow start.**

*What was wrong.* The rule above ("regenerate only when `bgm.m3u` is missing or older
than `settings.xml`") keys invalidation on the *settings*, not on the *source*. A
directory whose contents change without a settings change therefore keeps serving a
stale playlist indefinitely — the user rips a new album, it never plays, and nothing in
the UI or the log explains why. That directly violates **SC-005** ("100% of the files in
it matching a supported audio format are included in the BGM playlist the next time a
slideshow starts"), which `needs_regeneration`'s own docstring had claimed to satisfy
even though this decision's original rationale only ever justified **SC-004**. R-8 later
extended the same rule to `.pls`/`.xsp` without revisiting it, which made things worse:
a `.xsp` is a *live library query*, so caching its expansion is wrong by construction.
Found 2026-09-15 by an adversarial review of the whole working tree.

*What the cache was buying.* The only argument for it was the recursive `os.walk`'s cost
against SC-001's ~500 ms of headroom (2 s total, minus FR-013's 1 s fade and up to 0.5 s
of detection latency). So it was measured rather than argued about — synthetic nested
Artist/Album trees, `scan_directory` timed directly, on both filesystems present on the
dev machine, warm and then cold (page/dentry caches dropped via
`echo 3 > /proc/sys/vm/drop_caches` between the two passes):

| tracks | ext4 cold (warm) | fuseblk cold (warm) |
|---:|---:|---:|
| 500 | 19.4 ms (2.6) | 20.9 ms (10.0) |
| 1,000 | 37.1 ms (5.1) | 41.6 ms (19.4) |
| 5,000 | 49.0 ms (26.0) | 220.7 ms (101.6) |
| 10,000 | 57.9 ms (52.2) | 430.9 ms (207.2) |
| 20,000 | 116.3 ms (104.2) | 865.1 ms (411.5) |

Warm cost is linear at ~5.1 µs/track on ext4 and ~20.6 µs/track on fuseblk (FUSE pays a
userspace round trip per metadata operation). Cold costs a flat ~2.1× on fuseblk; on
ext4 the cold penalty is a fixed ~17 ms of filesystem warm-up that stops mattering as
the tree grows, so ext4 is a non-issue at any realistic size.

*Why the numbers did not save the cache.* Only one cell is genuinely over budget —
20,000 tracks on the slow filesystem, cold, at 865 ms. But **the cache does not fix that
case**: after any settings change, the very next slideshow pays the identical cold walk,
because that is exactly when the cache is invalid. The cache never eliminated a slow
first run; it only made one rarer. So the choice was never "fast vs. correct" but
"*occasionally* slow and always correct" vs. "*more rarely* slow and permanently wrong",
and the failure modes are not symmetric: a 0.4 s late fade-in is barely perceptible and
self-corrects, while a silently stale playlist is invisible, permanent, and reads to the
user as a broken addon.

*What replaced it.* `needs_regeneration`, `_is_newer_than` and `_uses_derived_m3u` are
gone; `_resolve_derived` always re-resolves. Two things keep that cheap and observable:

- `_regenerate` compares the freshly resolved track list against what `bgm.m3u` already
  holds and **skips the write entirely when they match**, leaving the file and its mtime
  untouched — so the common "nothing changed" case now touches the filesystem not at
  all. Direct content comparison, deliberately not a stored hash (the project owner's
  original suggestion): exact, no new persisted artifact, and the lists are at most a
  few thousand short strings. This composes with `write_m3u`'s temp-file replacement
  from the same day's work.
- `_regenerate` times the resolver and logs the elapsed milliseconds with the track
  count at `LOGDEBUG` (contracts/logging.md records the line's shape). The table above
  is synthetic, on one machine; this is how a genuinely slow real-world setup shows up
  in `kodi.log` instead of being guessed at.

One behavioral consequence, accepted deliberately: a `.pls` (or directory) that vanishes
*between* `config.validate` and `resolve` used to keep playing the previous `bgm.m3u`,
because the cache had no reason to invalidate. Now the source is re-resolved, finds
nothing, and BGM is disabled for that session with FR-012's notification — which is what
Edge Case 2 specifies for a source that has gone away, and it makes `.pls` behave like a
directory instead of differently. The previous `bgm.m3u` is still left byte- and
mtime-identical (`write_m3u` only replaces on a verified write), so a restored source
plays again next start. A source deleted *before* validation was already caught there as
`Reason.MISSING` and is unaffected.

The `_has_content` re-check that used to follow `_regenerate` in `_resolve_derived` was
also dropped: `_regenerate` now returns True only once the file provably holds a
non-empty list — either size-verified by its own write, or confirmed identical by
`_already_holds` — so the check had become unreachable by construction rather than
defensive.

*Known residual limit, recorded rather than hidden.* A very large library on slow
storage can still exceed SC-001 on a cold walk (865 ms of a ~500 ms budget at 20k tracks
on fuseblk). This is not a regression the cache was preventing — see above — and closing
it would need a different mechanism entirely (resolving off the critical path, or
relaxing SC-001), neither of which is justified by any observed case yet. Two related
gaps were noticed while measuring and are **not** addressed here: cold numbers come from
one machine's `drop_caches` runs, and network shares were never measured at all — the
latter partly because `scan_directory` uses `os.walk`, which cannot traverse an `smb://`
URL, so a network directory source appears to be unsupported today regardless of
caching. That is a functional gap worth its own investigation, not a caching question.

---

## D-010: User-facing messaging surfaces

**Decision**: map the spec's two notification classes onto Kodi's dialog APIs.

| Requirement | Surface | API |
|---|---|---|
| ~~FR-011 invalid source at settings time~~ | ~~Blocking, must acknowledge~~ | ~~`xbmcgui.Dialog().yesno(...)` to offer re-selection, `xbmcgui.Dialog().ok(...)` for the final "BGM disabled" notice~~ — **withdrawn 2026-09-15, unreachable in Script Mode; see the addendum below** |
| FR-012 playlist missing at slideshow start | Non-blocking toast | `xbmcgui.Dialog().notification(...)` |
| FR-015 skin integration failed at profile login | Non-blocking toast, detail in log | `xbmcgui.Dialog().notification(...)` naming the failure generically; `messages.log()` carries the specific reason and remedy |
| FR-009 all lifecycle logging | Kodi log | `xbmc.log('[slideshow-BGM] ' + msg, level)` |

**Rationale**: matches the 2026-09-09 clarifications exactly, extended 2026-09-11 for
FR-015. The split exists because the moments differ in what they may interrupt: at
settings time the user is already looking at a dialog-driven UI and blocking costs
nothing; at slideshow start or profile login a modal would interrupt playback FR-010
promises to leave running, or demand attention at a moment the user isn't necessarily
watching. FR-015's case follows FR-012's precedent rather than FR-011's: the failure is
real but not urgent enough to block anything, so the toast stays generic ("integration
failed, see log") and the specific reason plus a suggested remedy live only in the log —
consistent with FR-012's own notify-and-log split.

**Confidence**: High.

**Addendum (2026-09-15, the blocking half is withdrawn — it was never reachable)**: the
FR-011 row above describes a surface a Script Mode addon cannot raise. Kodi runs this
addon only when something launches it — the skin hook at slideshow start (D-007), or
the run-once service at profile login — so while the user is in the addon's settings
screen **no process of this addon exists** to show a dialog. Kodi's addon settings
dialog offers no callback for a changed `path` setting either: the only in-dialog hook
is a `type="action"` button the user must deliberately click, and
`xbmc.Monitor.onSettingsChanged` is delivered to an already-running interpreter, i.e.
only to resident services — which constitution principle 2.2 and this file's own D-007
both rule out for this addon.

`config.prompt_until_valid()` implemented that unreachable behavior faithfully and was
covered by six unit tests, but had **zero production call sites** — found 2026-09-15
while investigating where to trigger a new `.xsp` validation check. Tests for
unreachable code test nothing a user can experience, so the whole cluster was removed:
`prompt_until_valid`, its `_valid_source` helper, `messages.ok`, `messages.yesno`,
strings #32002/#32003, and the ten tests covering them (the CJK coverage among them was
retargeted at `notify`, which still exists).

D-010's table therefore collapses to **notify-only**: every surface this addon can
actually reach is non-blocking. `xbmcgui`'s blocking calls remain modeled in
`tests/fakes/xbmcgui.py` — the fake mirrors Kodi's API, not just the subset used — and
the assertions that *no* dialog is raised (`dialog_calls.ok_calls == []`) were kept as
regression guards. spec.md's FR-011 and Edge Case 1 were amended the same day; see its
Clarifications entry for 2026-09-15.

---

## D-011: Settings-UI grey-out for shuffle on `.pls`/`.xsp`

**Decision** (added 2026-09-11): disable the `random` toggle in the settings screen
whenever the selected source cannot honor it — a `.pls` or `.xsp` playlist (FR-008) —
using a settings `<dependencies>` `enable` condition, not addon Python code.

```xml
<setting id="random" type="boolean">
  ...
  <dependencies>
    <dependency type="enable">
      <or>
        <condition operator="is" setting="type">Directory</condition>
        <and>
          <condition operator="is" setting="type">Playlist</condition>
          <or>
            <condition operator="contains" setting="playlist">.m3u</condition>
            <condition operator="contains" setting="playlist">.M3U</condition>
          </or>
        </and>
      </or>
    </dependency>
  </dependencies>
</setting>
```

**Rationale**: checked against Kodi's own source
(`xbmc/settings/lib/SettingDependency.h` / `.cpp`) rather than assumed. The dependency
condition operator set is exactly four values:

```cpp
enum class SettingDependencyOperator { Unknown = 0, Equals, LessThan, GreaterThan, Contains };
```

parsed from the XML strings `is` / `!is`, `lessthan`/`lt`, `greaterthan`/`gt`,
`contains`/`!contains`. There is no `startswith` or `endswith` — a real file-extension
check is not expressible declaratively. `contains` is the closest fit: `!contains .pls`
and `!contains .xsp` against the `playlist` setting's full path string.

**Accepted imprecision**: `contains` matches a substring anywhere in the path, not a
suffix, so a path that happens to contain `.pls` or `.xsp` outside its extension (a
folder literally named `my.plsfiles`, say) would grey out `random` unnecessarily. This
is harmless rather than a merge blocker: the actual shuffle-ignoring behavior for these
formats is enforced at runtime by FR-008/`config.py`, not by this toggle's visual state.
The toggle greying out is an affordance, not the source of truth — if the heuristic ever
disagrees with reality, the worst outcome is a control that looks slightly wrong, not a
functional bug.

**Alternatives considered**:

- A hidden auxiliary setting updated by addon Python reacting to `onSettingChanged`,
  driving the `enable` condition indirectly — rejected: no simpler than the direct
  `contains` condition above, and adds a second setting to keep in sync for no benefit.
- Leaving `random` always enabled and relying only on FR-008's runtime behavior —
  rejected by the user in favor of the UI reflecting the constraint up front.
- A custom Python-driven settings dialog (`WindowXMLDialog`) with full programmatic
  control over widget state — rejected: abandons the standard Kodi settings screen
  principle 3.1 relies on, for a problem the declarative dependency system already
  solves well enough.

**Confidence**: High on the operator set (confirmed against source). **Hypothesis** on
whether the `contains` value comparison is case-sensitive — Kodi's own `type`/`playlist`
values are addon-chosen so case is controlled there, but a user-picked file's extension
case is not. If it proves case-sensitive, an uppercase `.PLS` file would fail to grey out
`random` — again cosmetic only, not a behavior bug. Verify in quickstart.md Tier 2 step 3.

**Addendum (2026-09-14, Tier 2 step 3 finding)**: the `<dependency>` block above
originally used two top-level sibling `<dependency type="enable">` elements (one per
branch) instead of the single `<or>`-wrapped one shown now. Real-Kodi testing showed
`random` permanently greyed out regardless of `type` — including with `type=Directory`,
which should unconditionally enable it. Root cause, source-verified against
`CSetting::IsEnabled()` in `xbmc/settings/lib/Setting.cpp`: sibling `<dependency>`
elements of the same `type` are combined with **AND**, not OR (it clears `enabled` on
the first failing dependency and never re-sets it). Two `enable` dependencies keyed to
mutually-exclusive `type` values is therefore an impossible condition — the toggle could
never be enabled by either branch alone. Fixed by nesting both branches inside one
`<dependency type="enable"><or>...</or></dependency>`. This generalizes beyond `random`:
any future multi-branch `enable`/`visible` dependency in this addon's settings.xml must
use an explicit `<or>` wrapper, never bare sibling `<dependency>` elements, unless AND
semantics are actually intended.

**Addendum (2026-09-14, second Tier 2 step 3 finding, same `random` dependency)**: after
the `<or>` fix above, re-testing found two more failures in the `Playlist` branch's
`!contains .pls`/`!contains .xsp` negated form: (1) `random` stayed enabled with `type=Playlist`
and `playlist=Not Selected`, since `Not Selected` contains neither substring; (2) `random`
stayed enabled for `my.PLS` (uppercase), confirming the case-sensitivity hypothesis this
decision originally flagged — source-verified,
`CSettingDependencyCondition::Check()` in `xbmc/settings/lib/SettingDependency.cpp`
compares with plain `std::string::find`, no case-insensitive form exists in the XML
schema at all. Fixed, per the user's suggestion, by flipping to a **positive** match —
`contains .m3u` OR `contains .M3U` — instead of negating `.pls`/`.xsp`. This resolves
both failures at once: `Not Selected` no longer matches either positive substring
(closing failure 1), and a positive whitelist is the safer default shape in general —
it fails closed for anything not explicitly listed (`Not Selected`, an unrecognized
future extension) instead of failing open the way the negated blacklist did. It does not
close every case permutation (`.M3u` is still unhandled), which is accepted for the same
reason D-011 already accepts this whole toggle as cosmetic: `playlist.py`'s runtime
enforcement already lowercases the extension and is unaffected by any of this.

**Addendum (2026-09-14, Tier 2 step 3 finding)**: the `playlist` setting's
`<control type="button" format="path">` was also wrong — `format="path"` calls Kodi's
`ShowAndGetDirectory()` (source-verified,
`CGUIControlButtonSetting::GetPath()` in `xbmc/settings/windows/GUIControlSettings.cpp`),
a folder-only browser that never applies the `<masking>` constraint. Real-Kodi testing
showed the file browser listing "0 items" for a directory that in fact contained
`my.m3u`/`my.pls`/`my.xsp` — the browser was filtering to subfolders only, not files at
all. Fixed by changing to `format="file"`, which calls `ShowAndGetFile()` with the
masking constraint passed through, matching what `contracts/settings.md`'s table already
documented (`playlist` | path (file)) but the implementation had diverged from.

**Addendum (2026-09-15, no standalone notice row exists in `settings version="2"`)**: an
attempt to add an always-visible informational line (stating that a selected playlist
must be a Music (Songs) source) as its own `<setting type="string">` with
`<control type="label" format="string"/>` rendered **nothing at all** on real Kodi — the
row was silently dropped, not shown blank. `CSettingControlLabel` (source-verified,
`xbmc/settings/SettingControl.cpp`) is real, but belongs to Kodi's core settings library;
the addon-settings dialog has no code path that instantiates a `label`-controlled row.
`type="lsep"` (a real, working notice mechanism in many published addons, confirmed via
a GitHub code search across `resources/settings.xml` files) is not an alternative either:
it is a `settings version` **1**-only token, converted by the old-format compatibility
parser (`CAddonSettings::ParseOldSettingElement` in
`xbmc/addons/settings/AddonSettings.cpp`) into a `CSettingGroup` label — the `version="2"`
deserializer this addon's `settings.xml` uses has no equivalent handling for it at all.

The only mechanism that actually shows explanatory text in the addon settings dialog is
a setting's own `help="..."` attribute (already used by every other setting here),
rendered in the info bar at the bottom of the window while that row has focus. Fixed by
folding the Music (Songs) requirement into the `playlist` setting's existing help string
(`#30021`) instead of adding a new row — which also satisfies "only when a playlist is
selected, not a directory" for free, since the `playlist` row (and so its help) is
already hidden entirely when `type` is `Directory`. `strings.po` supports a `\n` escape
for a forced line break within one `msgid` (confirmed via
`xbmc/guilib/GUITextLayout.cpp`'s `LineBreakText()`, which treats a literal `\n` as an
explicit break regardless of wrapping) — used here and on a few other multi-sentence
help/message strings for readability.

---

## D-012: Re-baseline volume so fades respect a deliberate mid-session change (resolves R-2)

**Decision** (user-confirmed 2026-09-12; now FR-016): `baseline_volume` stops being a
value captured once at session start. It is re-captured from the current volume at
every `PLAYING → SUSPENDED` transition (a video clip starting), and once more before an
end-of-session fade-out if the session was still `PLAYING`.

**Problem this closes**: as originally specified, every fade-`IN` ramped `0 →
baseline_volume` and the final `restore()` set volume back to `baseline_volume` — both
using the one value captured when the slideshow started. If the user raised or lowered
Kodi's volume deliberately while BGM was playing, the very next video clip's pause/resume
cycle — or the slideshow ending — would silently snap the volume back to the original
session-start level, discarding the user's change without any indication. Quickstart's
Tier 2 step 7 was already written to catch exactly this ("confirm the addon does not
fight the user or restore a stale baseline"), but nothing in D-003 or FR-013 actually
prevented it.

**Why re-capture at `PLAYING → SUSPENDED` specifically**: it is the last point at which
BGM (or, for a later clip, the previous re-baselined level) is audible before volume gets
forced to 0 — exactly the moment to sample "what the user last deliberately set it to."
Re-capturing at any other point either double-counts an already-silent volume (0, once
`SUSPENDED`) or requires a new event that does not otherwise exist.

**Cost**: one additional synchronous volume read (`capture_baseline()`, already defined
by D-003/contracts/modules.md) at an existing callback boundary. No new thread, no
polling loop — principle 1.1 is unaffected.

**Alternatives considered**:

- Leave a single frozen baseline and accept the risk as cosmetic — rejected: R-2's
  substantive half is a user-visible correctness bug (the addon overriding a deliberate
  user action), not cosmetic like the volume-OSD half of the same risk.
- Poll volume continuously to detect changes as they happen — rejected: reintroduces a
  sampler thread for a case fully covered by re-sampling at existing event boundaries.

**Confidence**: High — this is a control-flow change to when an existing, already-defined
read happens, not a new API dependency. The volume-OSD half of R-2 (some skins may show a
transient on-screen volume indicator during a programmatic ramp) is a separate,
mechanism-level question, closed by D-013.

---

## D-013: Set volume via the `SetVolume` builtin, not JSON-RPC, to suppress the OSD (fully resolves R-2)

**Decision** (user-confirmed 2026-09-12): every volume-*setting* call the fader makes —
the ramp steps and the inline snap-to-0 — uses `xbmc.executebuiltin("SetVolume(<percent>)")`,
not `xbmc.executeJSONRPC("Application.SetVolume", ...)`. Volume *reads* (for
`capture_baseline()` and re-baselining, D-012) are unaffected and stay on JSON-RPC
(`Application.GetProperties`), since reading volume has no OSD side effect.

**Why this was necessary, checked against Kodi master source directly (not the wiki,
which 403s to automated fetches — same limitation as R-4)**:

- The JSON-RPC method's own schema
  (`xbmc/interfaces/json-rpc/schema/methods.json`, `Application.SetVolume`) takes only a
  `volume` parameter — there is no flag to suppress anything.
- Its handler (`xbmc/interfaces/json-rpc/ApplicationOperations.cpp`,
  `CApplicationOperations::SetVolume`) posts `TMSG_VOLUME_SHOW`
  **unconditionally, on every call**:
  ```cpp
  appVolume->SetVolume(static_cast<float>(volume), true);
  ...
  CServiceBroker::GetAppMessenger()->PostMsg(TMSG_VOLUME_SHOW, up ? ACTION_VOLUME_UP : ACTION_VOLUME_DOWN);
  ```
  So the design as originally written (JSON-RPC throughout) would show/refresh the
  volume OSD on every single step of every fade — worse than R-2's original "may
  surface," which understated it.
- The builtin function's handler
  (`xbmc/interfaces/builtins/ApplicationBuiltins.cpp`, `SetVolume`) only posts that same
  message when the second argument is literally the string `"showVolumeBar"`:
  ```cpp
  if (params.size() > 1 && StringUtils::EqualsNoCase(params[1], "showVolumeBar"))
    CServiceBroker::GetAppMessenger()->PostMsg(TMSG_VOLUME_SHOW, ...);
  ```
  Omitted (as the fader will call it — `SetVolume(<percent>)` with no second argument),
  no OSD message is posted at all. This is a source-level guarantee, not an inference
  from documentation wording.

**Cost**: none — `xbmc.executebuiltin` is part of the `xbmc` module already listed as a
dependency (plan.md Technical Context); no new runtime dependency, no new thread.

**Alternatives considered**:

- Keep JSON-RPC and accept the OSD as unavoidable — rejected once the builtin's
  conditional gating was found in source; there is no reason to accept a cosmetic defect
  that has a zero-cost fix.
- Suppress the OSD post-hoc (e.g., hide the dialog window immediately after it shows) —
  rejected: racier and more code than simply not triggering it.

**Confidence**: High — verified against `xbmc/xbmc` master source (schema, JSON-RPC
handler, and builtin handler), the same standard of evidence D-011 used for the settings
dependency operators.

---

## D-014: Resuming BGM after a skipped clip must also unpause Kodi's own slideshow

**Decision** (Tier 2 bug report, 2026-09-17): `_on_clip_end` calls
`xbmc.executebuiltin("Action(Play)")` before resuming BGM whenever
`is_slideshow_paused()` (`Slideshow.IsPaused`) reads true.

**Symptom reported**: forcibly skipping a video clip (arrow key) during a slideshow
leaves BGM resuming normally, but the slideshow itself frozen on the next picture —
it never advances again. Letting the clip end naturally has no such problem.

**Root cause, verified against `xbmc/xbmc` master source
(`xbmc/pictures/GUIWindowSlideShow.cpp`)**, not guesswork:

- `OnMessage`'s `GUI_MSG_PLAYBACK_ENDED` case (natural end) clears `m_bPause` itself and
  advances `m_iCurrentSlide` in the same handler.
- `OnMessage`'s `GUI_MSG_PLAYBACK_STOPPED` case (any stop before natural end, which is
  what a forced skip produces — D-001's shared-callback finding) sets `m_bPause = true`
  and does nothing else. The one picture the user's keypress forces through still
  displays (driven independently by `m_bLoadNextPic` in `Process()`), but every
  *automatic* advance after that is gated on `!m_bPause` (line ~444:
  `bSlideShow = m_bSlideShow && !m_bPause && !m_bPlayingVideo`), which now never clears —
  matching D-002's already-recorded caveat that `Slideshow.IsPaused` is not an
  exclusively user-driven signal.
- Nothing else in Kodi's C++ clears `m_bPause` after a stop. `OnAction`'s shared
  `case ACTION_PAUSE: case ACTION_PLAYER_PLAY:` block is the only other write path: when
  the current slide is not a video and the slideshow is paused or inactive
  (`!m_bSlideShow || m_bPause`), *either* action resumes it (`m_bSlideShow = true;
  m_bPause = false;`); only `ACTION_PAUSE` can ever set it back to true.
  `xbmc.executebuiltin("Action(Play)")` maps to `ACTION_PLAYER_PLAY`
  (`xbmc/input/actions/ActionTranslator.cpp`, `{"play", ACTION_PLAYER_PLAY}`), which is
  therefore **not a toggle**: calling it while the slideshow is already unpaused hits
  neither of `OnAction`'s pause-related branches and is a no-op. (The real toggle,
  `ACTION_PLAYER_PLAYPAUSE` / `Action(PlayPause)`, is a different action and is not what
  this fix calls.)

**Why this is safe even called defensively**: the fix only fires when
`is_slideshow_paused()` already reads true, and `Action(Play)` cannot pause an
already-playing slideshow — so a false-positive read (e.g. a natural end observed at the
exact instant `Slideshow.IsPaused` has not yet been cleared) costs nothing.
`test_a_natural_clip_end_does_not_misfire_the_unpause_action`
(tests/integration/test_story2_video_clips.py) is the regression guard for that case.

**Confidence**: High on the mechanism (source-verified against `GUIWindowSlideShow.cpp`
and `ActionTranslator.cpp`, same standard of evidence as D-013). **Hypothesis, not yet
Tier-2-confirmed**: the exact interleaving of `m_iCurrentSlide`'s advance (driven by
`Process()`'s render loop) against this addon's callback dispatch is a timing question
source-reading cannot fully settle — `OnAction`'s `case ACTION_PAUSE: case
ACTION_PLAYER_PLAY:` block re-checks `IsVideo(m_slides.at(m_iCurrentSlide))` fresh at
dispatch time, and if that index somehow still pointed at the just-skipped clip, this
call would call `PlayVideo()` instead of unpausing. Reasoned unlikely (the slide index
advance does not wait on the stopped-video's own GUI message, and the builtin is itself
queued rather than dispatched synchronously), but must be confirmed against a running
Kodi before this is treated as fully closed — same category of risk as R-6/R-7.

---

## Probe results (2026-09-13)

T001 ran the scenario in
[tools/kodi-probe/README.md](../../tools/kodi-probe/README.md) against a real Kodi 21.3
instance, covering both the `.pls` and `.xsp` playlist formats end to end, each with a
slideshow containing two back-to-back video clips. The full log is saved at
`tests/manual/kodi-probe-run.log` (gitignored, per quickstart.md's fixture note).

Findings are folded into the relevant decisions above (D-001, D-002, D-003, D-005) and
into the risk list below. One finding did not fit any existing decision and is recorded
as new risk **R-7**: a video-renderer cold-start cost, paid once per slideshow session on
the first clip only.

`tests/fakes/` (T006) still needs to be reconciled against this log per quickstart.md
Tier 2 step 1 before Tier 1 results are trusted — that reconciliation is a separate,
not-yet-done implementation step; this probe run only settled what Kodi itself does.

## Resolved unknowns

| Unknown | Resolution | Status |
|---|---|---|
| Language/runtime floor | Python 3.8 (Kodi v20 Nexus); no 3.9+ syntax | Settled |
| How the addon is launched | D-007 skin `SlideShow.xml` onload hook | Mechanism settled, details to verify (Tier 2 step 2) |
| How slideshow start/end is detected | D-002 `Slideshow.IsActive` via Monitor wait loop | Condition names confirmed (2026-09-13 probe) |
| What happens to BGM when a clip starts | D-001 the shared player ends it; addon replays after | Confirmed (2026-09-13 probe): `onPlayBackStopped`, stream torn down |
| How BGM resumes | D-004 next track, uniformly for every source | Track-index reading confirmed for every source; `playoffset` honoring still to verify (Tier 2 step 5, needs addon code) |
| How the track index is known | D-005 `Playlist.Position(music)` read in `onAVStarted` | Confirmed populated for `.pls`/`.xsp` (2026-09-13 probe) |
| How fades are implemented | D-003 global volume ramp on all four transitions; D-012 re-baselines the ramp target to respect mid-session volume changes; D-013 sets volume via the `SetVolume` builtin (not JSON-RPC) to suppress the OSD | Settled (API fact, source-verified); clip-start timing measured (2026-09-13 probe) — see R-6/R-7 |
| How playback is started | D-006 `PlayMedia` builtin | Settled; `playoffset` support still to verify (needs addon code) |
| How the code is tested | D-008 in-repo fakes + Kodistubs | Settled |
| How the settings UI reflects the shuffle constraint | D-011 dependency `contains` condition | Operator set settled; value case-sensitivity to verify |

## Open risks carried into design

1. **R-1 — withdrawn (2026-09-10)**: `seekTime()` compatibility. D-004 removed
   `seekTime()` from the design. Kept as a placeholder so risk numbers stay stable.
2. **R-2 — fully resolved 2026-09-12 (D-012, D-013)**: global volume manipulation (D-003)
   was flagged as possibly surfacing a volume OSD, or racing with a user's own volume
   changes mid-slideshow. Both halves are now closed: D-012 re-baselines the fade target
   so a deliberate volume change survives; D-013 switches the set-volume call to the
   `SetVolume` builtin (source-verified to skip the OSD message when its optional
   argument is omitted), instead of JSON-RPC (source-verified to show it unconditionally).
3. **R-3 (medium)** — a skin update can overwrite `SlideShow.xml` and silently drop the
   hook (D-007), disabling the addon until the next profile login. Recorded in the spec
   as Edge Case 5.
4. **R-4 — resolved 2026-09-13 (probe)**: `Slideshow.IsActive`/`IsVideo` confirmed present
   and responsive on Kodi 21.3. `Slideshow.IsPaused` is also present, with the caveat
   recorded in D-002 (it reflects video playback too, not only a user-initiated pause).
5. **R-5 — resolved 2026-09-13 (probe)**: `Playlist.Position(music)` is populated with a
   usable, 1-indexed track number for both `.pls` and `.xsp` (see D-005). D-004's
   next-track resume design is viable for every source format. No longer blocks merge.
6. **R-6 (medium, refined 2026-09-13 by probe)** — the clip-start fade (D-003) assumes the
   addon is notified early enough to drop volume before the clip's audio is audible.
   Measured at ~0.2–0.4 s (warm renderer) and ~1.7 s (first clip of a session, see R-7).
   The steady-state number is small enough that FR-013's clip-start fade is not ruled out
   outright, but Tier 2 step 6 (quickstart.md) must confirm *audibly* whether even
   0.2–0.4 s produces a perceptible pre-dip burst — the probe measures wall-clock time,
   not what a human hears. If it does, FR-013's clip-start clause still has to be dropped.
7. **R-7 (new, medium, discovered 2026-09-13 by probe)** — a video-renderer cold-start
   cost adds roughly 1.3 s of extra latency, on top of the steady-state ~0.35 s, specific
   to the **first** video clip's `onAVStarted` in a slideshow session. Reproduced
   identically in both the `.pls` and `.xsp` scenario passes, each coinciding with a
   `CRenderManager::Configure - timeout waiting for configure` warning and an internal
   video-reopen retry in Kodi's own log. Not caused by this addon and not something addon
   code can shorten — it is Kodi's own renderer/GL-context initialization — but it means
   the first clip of every session is the one most likely to expose FR-013's
   full-volume-burst failure mode, even if later clips in the same session fade cleanly.
   No design change proposed; recorded so Tier 2 step 6 and T042 specifically watch the
   *first* clip of a session, not just any clip.
8. **R-8 (resolved 2026-09-14 by a design change, D-004 amended)** — real-device T041
   testing found `PlayMedia(<path>,playoffset=N)` does not honor `playoffset` at all for
   **both** `.xsp` smart playlists and `.pls` playlists: every resume after a clip lands
   back at track 1, regardless of `N`, for the entire session (`.pls` was first thought to
   be a side effect of the wrap-around fix in D-006's addendum above, since the original
   real-device report said "same as `.m3u`" — but a second, log-verified round showed
   `Playlist.Position(music)` genuinely stuck at `1` from the very first resume, identical
   to `.xsp`'s symptom, not a boundary-only bug). Kodi's own source
   (`PlayerBuiltins.cpp`, `MusicUtils.cpp`, `PlayListPLS.cpp`) shows both formats parsing
   and expanding correctly and going through the same `GetItemsForPlayList` →
   `playlistPlayer.Play(playOffset)` code path as the working `.m3u`/directory case, so the
   divergence was never root-caused further — it is treated as an empirically-confirmed
   Kodi limitation for these two formats, not chased into Kodi's own playlist-player
   internals.

   **Decision** (user-confirmed 2026-09-14): amend D-004. `.pls` and `.xsp` sources are now
   resolved by the addon itself into a concrete, ordered list of real track paths and
   flattened into the same derived `bgm.m3u` a `DIRECTORY` source already produces
   (`resources/lib/playlist.py`: `parse_pls()`, `resolve_xsp()`, both feeding the same
   `_resolve_derived()`/`needs_regeneration()`/`write_m3u()` scaffolding via a new
   `_uses_derived_m3u()` predicate) — `PlayMedia`'s `playoffset` is then only ever used
   against a plain `.m3u`, which real-device testing confirms works (including the D-006
   wrap-around fix). This is accepted as a deliberate, minimal widening of D-004's
   "no per-format branch" principle: the *resume mechanism* stays uniform (every format
   ends up as a plain `.m3u` handed to the same `player.py` code, unchanged), only the
   *source-to-track-list resolution* step is per-format now — and directory sources already
   established that precedent before this decision existed.
   - `parse_pls()`: pure Python, mirrors `CPlayListPLS::Load()`'s own philosophy —
     `NumberOfEntries` is a hint only (logged as a `LOGWARNING` on mismatch, per the user's
     explicit request), the actual `File<N>=` entries found are what's trusted.
   - `resolve_xsp()`: calls the same `Files.GetDirectory` JSON-RPC method Kodi's own
     "Browse into" smart-playlist UI uses (`CSmartPlaylistDirectory` →
     `CMusicDatabase::GetItems()`), via in-process `xbmc.executeJSONRPC` (no web
     server/remote JSON-RPC setting needed — that only gates *external* HTTP/TCP access,
     confirmed and explained to the user).
   - **Explicit, confirmed policy**: shuffle stays disabled for `.pls`/`.xsp` even after
     this change (FR-008/D-011 untouched) — `BgmSource.playlist_format`/`supports_shuffle`
     are computed from the original source path's extension, not the derived file, so
     `config.py`'s shuffle-forcing logic needed no change.

   **A second, distinct bug found while first testing this fix (2026-09-14)**: the first
   `.xsp` attempt failed with a Kodi-logged
   `JSONRPC: Array element at index 1 does not match in type properties` /
   `malformed Files.GetDirectory response` — `resolve_xsp()` had requested
   `properties: ["file", "filetype"]`, but Kodi's own JSON-RPC schema
   (`List.Fields.Files`'s enum, `xbmc/interfaces/json-rpc/schema/types.json`) does **not**
   include `filetype` as a requestable property at all — it is always present in the
   response regardless (`List.Item.File.filetype` is marked `required: true` in the same
   schema). Requesting it makes Kodi reject the entire call as a schema violation. Fixed by
   dropping it from the request (`properties: ["file"]`); a regression test
   (`test_resolve_xsp_never_requests_filetype_as_a_property`) pins the exact request shape
   sent, since the fake's `Files.GetDirectory` stub does not itself replicate Kodi's schema
   validation and so could not have caught this any other way.

   **Status**: `.pls` re-tested and confirmed working end-to-end on real Kodi (correct
   per-clip advancement, and the last-track wrap-around from D-006's addendum too, since it
   now goes through the exact same derived-`.m3u` path directory sources use). `.xsp`
   re-test with the `properties` fix is pending.

   **Addendum (2026-09-14, robustness improvement, user-requested)**: `parse_pls` now
   also checks each resolved `File<N>=` entry with `xbmcvfs.exists` and drops any that
   does not point to a real file, so a stale reference in a hand-edited or out-of-date
   `.pls` never ends up in the derived `bgm.m3u` (a `LOGWARNING` names how many entries
   were skipped, out of how many total, when at least one is). This is independent of the
   `NumberOfEntries` mismatch check above — one is about the file's own header lying
   about its line count, the other is about whether a correctly-parsed entry's target
   still exists on disk. Not extended to `.xsp`: its entries come from Kodi's own music
   library query (`Files.GetDirectory`), which by construction only returns files the
   library already knows about.

   **Addendum (2026-09-14, third and fourth `.xsp` bugs found and fixed, real-device T041
   re-test)**: after the `properties` fix above, `tests/manual/slideshow-fixtures/playlists/my.xsp`
   (an arbitrary repo-local path) resolved and played correctly end to end — including
   the last-track wrap-around from D-006's addendum. But a second `.xsp`, saved at Kodi's
   own **default** smart-playlist location (`special://musicplaylists/`, i.e.
   `~/.kodi/userdata/playlists/music/`) and selected the normal way through the addon's
   settings file-browse dialog, still failed: `{"error":{"code":-32602,"message":"Invalid
   params."}}`, alongside a Kodi-logged `CUtil::GetMatchingSource: no matching source
   found for [<the .xsp's resolved absolute path>]`.

   Root cause, source-verified: `Files.GetDirectory`'s handler
   (`CFileOperations::GetDirectory` in `xbmc/interfaces/json-rpc/FileOperations.cpp`)
   calls `CFileUtils::RemoteAccessAllowed(strPath)` (`xbmc/utils/FileUtils.cpp`) and
   rejects the request outright if it returns false. That function only allows a fixed
   set of protocol roots (`special://musicplaylists/` among them) or a path matching an
   already-registered, non-locked, shareable media source — an arbitrary absolute
   filesystem path matches neither. The addon's settings `playlist` path setting stores
   whatever Kodi's own file-browse dialog gives back for a chosen file, which resolves a
   `special://musicplaylists/<name>.xsp` selection down to its plain absolute path (this
   is normal, expected dialog behavior, not a bug) — so by the time `resolve_xsp()` ever
   sees it, the very `special://` form that would have been accepted is already gone.

   First fix attempt: `_prefer_special_musicplaylists()`, called by `resolve_xsp()` before
   the JSON-RPC call, comparing `path` against `xbmcvfs.translatePath("special://
   musicplaylists/")`'s resolved root and rewriting it back to `special://` form when it
   falls under that root. Real-device re-testing immediately surfaced a **fourth, more
   subtle bug**: `translatePath("special://musicplaylists/")` does not return a single
   real directory at all — it returns a `multipath://` URI verbatim:
   `multipath://special%3a%2f%2fprofile%2fplaylists%2fmusic/special%3a%2f%2fprofile%2fplaylists%2fmixed/`,
   Kodi's own union of `special://profile/playlists/music/` *and*
   `special://profile/playlists/mixed/` (its combined view of pure-music and mixed
   playlists). A `multipath://` string can never prefix-match a plain resolved absolute
   path, so the rewrite silently never triggered.

   Final fix: key off `special://profile/playlists/music/` directly instead of
   `special://musicplaylists/` — one of the two real directories the multipath alias
   hides, and confirmed (both by the decoded multipath value above and by
   `CFileUtils::RemoteAccessAllowed`'s own source) to be a location `Files.GetDirectory`
   accepts on its own, via its separate `special://profile/` allow-list entry. Scoped to
   this one root only — it is Kodi's own default, overwhelmingly common save location for
   a music smart playlist created through Kodi's own UI, and this addon only ever resolves
   `.xsp` for `media="music"`; a `.xsp` living somewhere else entirely (not under this root
   and not a registered, shareable source) remains a real, accepted limitation of
   `Files.GetDirectory` itself, not something this addon can work around generally.

   **Status**: confirmed working end-to-end on real Kodi (2026-09-14) — an `.xsp` saved at
   `special://musicplaylists/` and picked via the addon's normal settings file-browse
   dialog now resolves, plays, and (per D-006's addendum) wraps correctly.

   **Addendum (2026-09-15, non-music smart playlist gap, user-requested)**: `resolve_xsp`
   calls `Files.GetDirectory` with `media: "music"`, but that parameter only hints how
   Kodi interprets the browse — it does not restrict which `.xsp` files the addon may
   point at. A Kodi smart playlist's root `<smartplaylist type="...">` attribute accepts
   several values, source-verified against `CSmartPlaylist::readName()` in
   `xbmc/playlists/SmartPlayList.cpp` on the Kodi GitHub repo: `songs`, `albums`,
   `artists`, `movies`, `tvshows`, `episodes`, `musicvideos`, `mixed`, plus a legacy
   `music` alias Kodi itself normalizes to `songs`. Only `songs`/`music` is guaranteed to
   resolve to individual playable *audio* files — a `movies`/`musicvideos`/`mixed` smart
   playlist can still return real, playable *video* files (`filetype: "file"`, passing
   `resolve_xsp`'s existing filter unchanged), which would silently end up in the derived
   `bgm.m3u` as if they were background music tracks.

   **Fix**: a new `playlist.is_music_smartplaylist(path)` reads the `.xsp` XML directly
   (never via JSON-RPC) and checks the root `<smartplaylist>` element's `type` attribute,
   normalizing the legacy `music` alias to `songs`. `config.validate()` gained a 4th
   ordered check — `Reason.NOT_MUSIC_PLAYLIST` — inserted between the existing `MISSING`
   and `EMPTY` checks (contracts/settings.md), so a wrong-type `.xsp` is rejected before
   the `Files.GetDirectory` round-trip runs at all, whether or not that round-trip would
   have happened to yield anything. On failure, this specific case gets its own
   error-icon, error-worded non-blocking notification (`#32005`,
   `xbmcgui.NOTIFICATION_ERROR`) distinct from every other validation failure's generic
   `#32004` informational toast (`session.py`'s `_disable()` gained optional
   `message`/`icon` parameters, defaulting to today's exact behavior for every other
   `Reason`) — the user asked specifically for the wrong-type case to read as an error,
   not a routine "nothing configured" notice. The specific type found (or "malformed
   XML"/"wrong root element") is logged at `LOGWARNING`/`LOGERROR` by
   `is_music_smartplaylist` itself, not by `config.py`/`session.py`, matching how
   `parse_pls`/`resolve_xsp` already self-log their own diagnostics rather than pushing
   detail up to their callers.

   **Confirmed on real Kodi (2026-09-15)**: a `type="movies"` `.xsp` produces
   `WARNING: .../sample.xsp is a smartplaylist type="movies", not a music (songs)
   playlist` followed by `INFO: BGM disabled: not_music_playlist` in `kodi.log`, and the
   error-styled notification (distinguishable icon/sound from the routine toast) with no
   BGM playback attempted; a `type="songs"` `.xsp` is unaffected and plays normally.
