# Phase 1 Data Model: Slideshow Background Music Playback

**Branch**: `001-slideshow-bgm-playback` | **Created**: 2026-09-09 | **Last revised**: 2026-09-15

All state is in-memory and lives exactly as long as one Script Mode process
(Assumption 2, FR-004). The only persisted artifacts are Kodi's own `settings.xml` and
the derived `bgm.m3u`. Terminology follows [spec.md](./spec.md); where the spec's
user-facing wording differs from the mechanism, the difference is noted and traced to
[research.md](./research.md).

---

## BgmSource

The user-selected origin of background music, resolved from addon settings at session
start.

| Field | Type | Source | Notes |
|---|---|---|---|
| `kind` | `SourceKind` enum: `PLAYLIST` \| `DIRECTORY` | setting `type` | FR-005 |
| `path` | `str` | setting `playlist` or `directory` | `"Not Selected"` sentinel means unconfigured |
| `shuffle` | `bool` | setting `random` | FR-008 |
| `resolved_playlist` | `str` | derived | Absolute path actually handed to `PlayMedia` |
| `playlist_format` | `PlaylistFormat` enum: `M3U` \| `PLS` \| `XSP` | derived from extension | Drives `supports_shuffle` |

**Derived properties**

- `supports_shuffle` — `True` for `M3U` (including the directory-derived `bgm.m3u`);
  `False` for `PLS` and `XSP`, whose native order wins (FR-008).

There is deliberately **no** offset- or seek-related property here. D-004 made resume
uniform across every format — always the following track — so nothing in the *resume*
path branches on `playlist_format`. R-8 (research.md) amended D-004 for the *source
resolution* step only: real-device testing found Kodi's own `playoffset` never advances
past track 1 for `.pls`/`.xsp`, so `resolve()` now derives a concrete `bgm.m3u` for those
two formats as well as for `DIRECTORY` (see below) — `player.py`'s resume mechanism
itself still never branches on format, since by the time it runs, every source has
already become a plain `.m3u`.

**Validation rules**

| Rule | Requirement | Failure surface |
|---|---|---|
| `path != "Not Selected"` | FR-010 | Silent skip at slideshow start — nothing configured is not an error (US1 scenario 3) |
| `xbmcvfs.exists(path)` | FR-012 | Non-blocking notification, slideshow continues without BGM |
| `.xsp` only: root `<smartplaylist type="...">` is `songs`/`music` (R-8, 2026-09-15) | FR-012 | Non-blocking, **error-styled** notification (`#32005`) distinct from the other rows' generic toast; slideshow continues without BGM |
| Resolved playlist has ≥ 1 entry | FR-010, FR-012 | Non-blocking notification at slideshow start |
| Extension ∈ `{.m3u, .pls, .xsp}` | FR-007 | Enforced by settings `<masking>` |

**Directory resolution** (FR-006, D-009): recursively walk `path` as **bytes** (Kodi's
ASCII `filesystemencoding` raises `UnicodeError` on non-ASCII names handled as `str`),
match `{.mp3, .wav, .ogg, .wma, .flac, .aac, .m4a}` case-insensitively, and write
`bgm.m3u` to the addon profile directory. Re-resolved on **every** slideshow start
(SC-004, SC-005), with the file write skipped whenever the resolved list matches what
`bgm.m3u` already holds. The mtime cache this once used was removed 2026-09-15 — it
keyed invalidation on `settings.xml` alone, so a directory whose contents changed served
a stale playlist forever (D-009's third addendum carries the measurements).

**`.pls`/`.xsp` resolution** (R-8, added 2026-09-14): these two formats derive the same
`bgm.m3u` too, re-resolved on every start exactly as directory sources are, but each
gets its own track list a different way:

- `.pls`: parsed directly (`parse_pls`) — `NumberOfEntries=` is only a hint, never
  trusted; the actual `File<N>=` entries found are what's used, and any entry whose
  resolved path does not exist (`xbmcvfs.exists`) is dropped before the list is written,
  so a stale reference in the `.pls` never ends up in `bgm.m3u`.
- `.xsp`: resolved via the same `Files.GetDirectory` JSON-RPC call Kodi's own
  smart-playlist "Browse into" UI uses (`resolve_xsp`), run in-process via
  `xbmc.executeJSONRPC` — no web-server/remote-control setting needed. That call only
  accepts a `special://`-style path or an already-registered, shareable source, so an
  `.xsp` under Kodi's own default save location is rewritten back to its
  `special://profile/playlists/music/` form before the call
  (`_prefer_special_musicplaylists`) — the addon's settings dialog otherwise stores it
  as a plain absolute path, which `Files.GetDirectory` rejects.

`shuffle`/`supports_shuffle` are unaffected by this: both stay computed from the
*original* `.pls`/`.xsp` path's extension, not the derived file, so FR-008's "own native
order" policy for these two formats is unchanged by how they're now resolved.

---

## SlideshowSession

One run of a slideshow, owning every other object. Created by `addon.py` when the skin
hook fires; destroyed when `Slideshow.IsActive` goes false or Kodi aborts (FR-004).

| Field | Type | Notes |
|---|---|---|
| `state` | `SessionState` | See state machine below |
| `source` | `BgmSource` \| `None` | `None` once BGM is disabled for this session |
| `baseline_volume` | `int` (0–100) | Captured at start; re-captured before each pause-for-clip and before an end-of-session fade-out from `PLAYING`, so it always reflects the volume last observed while BGM was audible (FR-016); restored on every exit path (D-003) |
| `position` | `BgmPosition` | Which track to resume after (no sampler behind it) |
| `existing_playback_policy` | `TAKE_OVER` \| `YIELD` | setting `on_existing_playback`, default `TAKE_OVER` (FR-014) |

### SessionState

```text
STARTING ──valid source──> PLAYING ──video clip starts──> SUSPENDED
    │                         ▲                               │
    │                         └────image slide resumes────────┘
    │                                                         │
    └──no/invalid source──> DISABLED                          │
                                │                             │
    Slideshow.IsActive false or abortRequested  ◄─────────────┘
                                │
                                ▼
                          TERMINATED
```

| Transition | Trigger | Actions |
|---|---|---|
| `STARTING → PLAYING` | Valid source, and policy allows (FR-014) | Capture baseline volume, prime shuffle/repeat, `PlayMedia`, fade in (FR-001, FR-013) |
| `STARTING → DISABLED` | No source, unreadable source, a non-music `.xsp`, or empty playlist, or policy `YIELD` with audio already playing | Log always; notify per FR-012 for a source the user configured but that cannot be used (never for "nothing configured"); slideshow proceeds silently (FR-010) |
| `PLAYING → SUSPENDED` | `onPlayBackStopped`/`onPlayBackEnded` while `Slideshow.IsVideo` | Re-capture `baseline_volume` from the current volume, then freeze `track_index`; drop volume to 0 and fade the **clip's** audio in — the BGM stream is already gone (D-001, D-003, FR-016) |
| `SUSPENDED → PLAYING` | Playback callback fires and the next slide is not a video | `PlayMedia` at `resume_offset(position)` (`track_index + 1`, wrapped to `1` at the playlist's end — see `BgmPosition` below), fade in to `baseline_volume` (FR-003) |
| `SUSPENDED → SUSPENDED` | Next slide is another video clip | Stay silent (FR-003 second clause, Edge Case 4) |
| any `→ TERMINATED` | `Slideshow.IsActive` false, or `Monitor.abortRequested()` | If leaving `PLAYING`, re-capture `baseline_volume` first (FR-016); fade out (only from `PLAYING`), stop player, join the fade thread, restore `baseline_volume` (FR-004) |

`TERMINATED` is absorbing: BGM never resumes afterwards (FR-004, Edge Case 3).

**Note on naming**: the spec's **BGM Pause** entity maps to `SUSPENDED`. It describes a
suspended stream; the mechanism is stop-and-replay because Kodi destroys the stream when
a video clip claims the player (D-001). Observable behavior is unchanged.

---

## BgmPosition

The resume point: which track was playing when a clip interrupted. Nothing else — D-004
removed elapsed time from the design entirely, so there is no offset field and no sampler
thread behind this entity.

| Field | Type | Updated by | Notes |
|---|---|---|---|
| `track_index` | `int` | `onAVStarted` callback | Read from `xbmc.getInfoLabel('Playlist.Position(music)')` (D-005) |
| `track_count` | `int` | `onAVStarted` callback | Read from `xbmc.getInfoLabel('Playlist.Length(music)')`; `0` when never read or the read failed (added 2026-09-14, T041) |
| `is_valid` | `bool` | derived | `False` before the first `onAVStarted`, or when the position infolabel read failed |

**Reading the index** (D-005): `getInfoLabel` returns a **string**, empty when nothing is
playing, so `int()` on it raises `ValueError`. Every read is guarded, and a failed read
leaves `is_valid` `False`. `track_count`'s read is guarded the same way, but a failed
*length* read does not invalidate an otherwise-successful *position* read — it just
leaves `track_count` at `0` (research.md D-006's addendum).

**Resume algorithm** (FR-003, D-004) — one path, every format:

1. `PlayMedia(playlist, playoffset=resume_offset(position))` — the track **after** the
   one that was playing, from its beginning: `track_index + 1`, **wrapped to `1`** when
   that would exceed `track_count` (real Kodi clamps an out-of-range `playoffset` to the
   last track rather than wrapping it itself — T041 finding, research.md D-006's
   addendum — so the addon computes the wrap). When `is_valid` is `False`, use
   `playoffset=0` and restart the playlist rather than guessing. When `track_count` is
   unknown (`0`), falls back to the unwrapped `track_index + 1` — no regression versus
   before this fix existed.
2. Fade in (D-003).

No seek, no per-format branch in this step itself — by the time it runs, `playlist` is
always a plain `.m3u` (R-8 amended D-004 one step earlier, at source resolution; see
`BgmSource` above). This still rests on a track being targetable at all — risk R-5,
reasoned through in research.md D-005.

---

## Fade

A bounded global-volume ramp, applied at all four transitions (D-003, FR-013).

| Field | Type | Notes |
|---|---|---|
| `direction` | `IN` \| `OUT` | |
| `duration_ms` | `int` | 1000 (FR-013) |
| endpoints | fixed, not parameters | `IN` always runs 0 → `baseline_volume`; `OUT` always runs current → 0 |

Volume is *set* via the `SetVolume` builtin (`xbmc.executebuiltin("SetVolume(<percent>)")`),
never JSON-RPC — D-013 found that JSON-RPC's `Application.SetVolume` shows Kodi's volume
OSD unconditionally on every call, with no way to suppress it, while the builtin only
shows it when explicitly asked to. Volume is still *read* via JSON-RPC
(`Application.GetProperties`) for `capture_baseline()`, since reads have no OSD side
effect. Kodi exposes no per-player volume either way, so every ramp moves **all** audio.
Which stream a given fade actually shapes therefore depends on what is audible at that
moment:

| Transition | What the ramp acts on |
|---|---|
| Slideshow start, clip end, slideshow end | Background music |
| **Clip start** | The **clip's** audio — the BGM stream is already gone (D-001) |

The clip-start ramp must reach 0 before the clip's audio is audible, or the user hears a
burst at full volume followed by a dip (risk R-6) — which is why the snap to 0 runs inline
on the callback thread (see [contracts/modules.md](./contracts/modules.md), `fader`). The
clip's audio is deliberately *not* faded out at the clip's end: that would mean watching
the clip's remaining time, reintroducing the kind of sampler thread D-004 just removed.

**Invariant**: whatever happens, `baseline_volume` is restored before the process exits.
A fade in progress at teardown is cancelled, not awaited.

**Re-baselining (FR-016, resolves R-2's correctness half)**: `baseline_volume` is not
captured once and frozen — it is re-captured from the current volume at every
`PLAYING → SUSPENDED` transition, and once more before an end-of-session fade-out if the
session was still `PLAYING`. This is what lets a deliberate volume change the user makes
while BGM is audible become the new fade-in/restore target, instead of being overwritten
by the next transition or by the final restore. The re-capture is a single synchronous
volume read at an existing callback boundary — no new thread or polling.

**OSD suppression (D-013, resolves R-2's remaining half)**: because every ramp step and
the inline snap-to-0 set volume via the `SetVolume` builtin without its optional
`showVolumeBar` argument, none of them trigger Kodi's on-screen volume indicator.

---

## SkinHook

The `<onload>` element the addon maintains in the active skin's `SlideShow.xml` (D-007).
Not part of the slideshow session — installed at profile login and inspected only by
`service.py` and `skinconnector.py`.

| Field | Type | Notes |
|---|---|---|
| `slideshow_xml_path` | `str` | Located by walking `special://skin` for `SlideShow.xml` |
| `is_hooked` | `bool` | Whether the addon's `<onload>` element is present |
| `is_writable` | `bool` | Both the file and its directory must be writable |
| `backup_path` | `str` | `<slideshow_xml_path>.original`, written before first edit |

See [contracts/skin-integration.md](./contracts/skin-integration.md) for the exact
element.

---

## Entity relationships

```text
SlideshowSession 1 ──── 0..1 BgmSource      (None once BGM is disabled)
SlideshowSession 1 ──── 1    BgmPosition
SlideshowSession 1 ──── 0..1 Fade           (at most one ramp in flight)
SkinHook          ──── standalone, outlives every session
```
