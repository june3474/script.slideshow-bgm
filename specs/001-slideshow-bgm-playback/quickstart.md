# Phase 1 Quickstart: Validation Guide

**Branch**: `001-slideshow-bgm-playback` | **Created**: 2026-09-09 | **Last revised**: 2026-09-11

How to prove this feature works, end to end. Two tiers, because Kodi's Python API is a set
of C++ bindings that cannot be installed into a virtualenv
([research.md D-008](./research.md)):

- **Tier 1 — automated** (`pytest` against in-repo fakes): everything that is logic.
- **Tier 2 — manual in Kodi**: settings rendering, real callback ordering, and the real
  behavior of `Playlist.Position(music)`. The constitution's Development Workflow makes
  these mandatory before merge, not optional extras.

Green tests alone do not close this feature. Tier 2 is where risks R-2 through R-6
([research.md](./research.md)) are actually retired.

> **Run Tier 2 step 1 (the probe) first.** It is listed under Tier 2 because it needs a
> running Kodi, but it comes before everything else in time: until it has run, the fakes
> Tier 1 depends on encode assumptions rather than observed behavior.

---

## Prerequisites

| Need | For |
|---|---|
| Python 3.8+ (3.8 is the syntax floor, not just the minimum) | Tier 1 |
| `pytest`, `Kodistubs`, `ruff`, `mypy` — dev-only, zero runtime deps | Tier 1 |
| Kodi v20 (Nexus) or newer | Tier 2 |
| A directory of audio files including at least one non-ASCII filename | Tier 2, D-009 |
| One `.m3u`, one `.pls`, and one `.xsp` playlist — samples at `tests/manual/slideshow-fixtures/playlists/{my.m3u,my.pls,my.xsp}`, all three covering the same 10 tracks (copied into `bgm-source/`), 2 with Korean filenames for the D-009 non-ASCII case | Tier 2, FR-007/FR-008 |
| A slideshow folder mixing images with at least two consecutive video clips — sample set at `tests/manual/slideshow-fixtures/slideshow-source/` (gitignored, not part of the repo) | Tier 2, US2 |

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"        # pytest, Kodistubs, ruff, mypy from pyproject.toml
```

There is nothing to build. For Tier 2, symlink or copy the repo into Kodi's addon
directory and restart Kodi:

```bash
ln -s "$PWD" ~/.kodi/addons/script.slideshow-bgm
```

---

## Tier 1 — automated

### Quality gates (constitution 6.2, CI-blocking, zero warnings)

```bash
ruff check .
ruff format --check .
mypy --strict .
pytest
```

All four must pass. `mypy --strict` resolves `xbmc*` through Kodistubs; `pytest` resolves
them through `tests/fakes/` injected into `sys.modules` by `conftest.py` — the fakes must
win at test time, which is what `conftest.py` guarantees by importing before anything
else.

### What the fakes must model

These are not incidental test details; they are the findings the feature is built on, and
a fake that does not model them lets a broken implementation pass:

| Fake behavior | Encodes |
|---|---|
| Starting video playback **destroys** the audio stream and fires `onPlayBackStopped`/`onPlayBackEnded` | D-001 |
| `Slideshow.IsActive` / `IsVideo` / `IsPaused` are settable per test | D-002 |
| A single global volume register, readable via JSON-RPC and writable via the `SetVolume` builtin | D-003, D-013 |
| `Playlist.Position(music)` is a settable infolabel, and returns `''` when nothing plays | D-005 |
| `PlayMedia` records the `playoffset` it was given, so tests can assert the target track | D-004 |

The fakes' shape must be reconciled against the probe's log (Tier 2 step 1) before the
tests are trusted — they encode what this design *believes* Kodi does.

### Story-level scenarios

Run one file per story so a story can be validated independently, as its spec entry
requires:

```bash
pytest tests/integration/test_story1_playback.py -v      # US1 - P1
pytest tests/integration/test_story2_video_clips.py -v   # US2 - P2
pytest tests/integration/test_story3_configuration.py -v # US3 - P3
```

| Scenario | Expected | Traces |
|---|---|---|
| Valid source, slideshow starts | Player receives `PlayMedia`; volume ramps to baseline | FR-001, SC-001 |
| Slideshow goes inactive | Fade out, stop, threads joined, **volume restored to baseline** | FR-004, SC-003 |
| No source configured | No player call, no dialog, no exception | US1 sc. 3, FR-010 |
| Video clip starts | State `SUSPENDED`, `track_index` frozen, volume dropped to 0 then ramped to baseline | FR-002, FR-013, D-003 |
| Video clip ends, next slide is an image | `PlayMedia` with `playoffset == frozen_index + 1`, fade in | FR-003, SC-002 |
| Two clips back to back | Stays `SUSPENDED` across both; exactly one suspend, one resume | US2 sc. 3, Edge Case 4 |
| Clip interrupts track N, any source | Resumes at the **beginning of track N+1** — same assertion for `.m3u`, `.pls`, `.xsp` and directory | FR-003, D-004 |
| `Playlist.Position(music)` returns `''` | `is_valid` `False`; resume falls back to `playoffset=0`, no crash | D-005 |
| Directory source | All seven FR-006 extensions collected; non-ASCII name survives | SC-005, D-009 |
| A track added to the directory since the last run | Appears on the next slideshow — every derived source is re-resolved each start | SC-005, D-009 addendum |
| Resolved list identical to the cached `bgm.m3u` | File not rewritten; mtime unchanged | D-009 addendum |
| Policy `Yield` with audio already playing | Straight to `DISABLED`, existing playback untouched | FR-014, US3 sc. 5 |

### The invariant worth its own test

Volume restoration is the one failure the user cannot recover from without noticing
Kodi is broken. Assert it on **every** exit path — clean end, abort request, and an
exception raised mid-fade:

```bash
pytest tests/unit/test_fader.py -k restore -v
```

---

## Tier 2 — manual in Kodi

Automated tests cannot reach any of the following. Work through them in order; each maps
to a risk or to a constitution requirement that explicitly defers to manual checking.

Steps 1–2 measure Kodi and need no addon code. Steps 3–7 confirm the finished addon
behaves as the measurements predicted.

### 1. Probe run — before any implementation code

Follow [`tools/kodi-probe/README.md`](../../tools/kodi-probe/README.md). One run settles
every **Hypothesis** in [research.md](./research.md) except the ones that are pixels:
which callbacks fire when a clip takes the player (D-001), the real `Slideshow.*`
condition names and timing (D-002, R-4), whether `Playlist.Position(music)` is populated
for `.pls`/`.xsp` (D-005, R-5), and how quickly the clip-start callback arrives (D-003,
R-6).

Reconcile `tests/fakes/` against the resulting log before trusting any Tier 1 result.

### 2. Skin hook install (D-007, R-3)

1. Start Kodi with the addon installed. Confirm `SlideShow.xml` in the active skin now
   contains the `<onload>` element from
   [contracts/skin-integration.md](./contracts/skin-integration.md), and that
   `SlideShow.xml.original` exists beside it.
2. Restart Kodi. Confirm **exactly one** `<onload>` — the hook must be idempotent.
3. Switch skins, restart, confirm the new skin is hooked.
4. Make the skin directory read-only, restart: a `LOGERROR` line naming the "not
   writable" reason and its remedy (see
   [contracts/skin-integration.md](./contracts/skin-integration.md) for the exact
   pairs), plus one non-blocking notification — no crash, no blocking dialog.

### 3. Settings UI (constitution: settings rendering is not unit-testable)

Open the addon settings and confirm against
[contracts/settings.md](./contracts/settings.md): `playlist` and `directory` show and
hide with `type`; the file mask accepts only `.m3u`/`.pls`/`.xsp`; defaults are
`Not Selected`, `random` on, `on_existing_playback` = `TakeOver`; every label and help
string is localized, with no raw string ids visible.

Then pick an empty directory and **start a slideshow**: BGM is disabled with a
non-blocking notification and a logged reason, and the slideshow plays on (FR-012).
There is no settings-time dialog to look for — FR-011's was withdrawn 2026-09-15 as
unreachable in Script Mode (spec.md's Clarifications for that date).

Also confirm the `random` grey-out (D-011): select a `.m3u` playlist
(`tests/manual/slideshow-fixtures/playlists/my.m3u`) or a directory
(`tests/manual/slideshow-fixtures/bgm-source/`) — `random` is enabled; select a `.pls`
or `.xsp` file (`tests/manual/slideshow-fixtures/playlists/my.pls` / `my.xsp`) —
`random` greys out. Try an uppercase-extension file too
(`.PLS`) — this exercises the case-sensitivity hypothesis in D-011; note whether it
greys out or not either way, since the toggle's visual state is cosmetic and does not
gate FR-008's actual runtime behavior.

### 4. The addon's own log (contracts/logging.md)

Run a slideshow over `tests/manual/slideshow-fixtures/slideshow-source/` (mixed images
and clips) while tailing the log:

```bash
tail -f ~/.kodi/temp/kodi.log | grep '\[slideshow-BGM\]'
```

Confirm the sequence matches [contracts/logging.md](./contracts/logging.md), and that no
`session end` line is missing after any exit. Check the restored-volume value in that
line against the volume you started with.

### 5. Track targeting across formats — risk R-5

Step 1 answers whether this *can* work; this step confirms the addon actually does it. For
each of `.m3u`, `.pls`, `.xsp` (use `tests/manual/slideshow-fixtures/playlists/my.m3u`,
`my.pls`, `my.xsp`) and a directory source (`tests/manual/slideshow-fixtures/bgm-source/`
— the same 10 tracks), let a clip interrupt track N and confirm playback resumes at the
**beginning of track N+1**.

### 6. Clip-start fade timing — risk R-6

Watch a clip begin with BGM playing. The clip's audio must fade in from silence; if you
hear a burst at full volume before the dip, the snap to 0 is landing too late and FR-013's
clip-start clause has to be dropped. Step 1's timestamps predict this; this step is the
audible confirmation.

### 7. Fade side effects and mid-session volume changes — FR-016, D-012, D-013 (resolves R-2)

Confirm no volume OSD appears during any fade or the clip-start snap — D-013 switched
volume-setting to the `SetVolume` builtin specifically to suppress it, so this should now
be a hard pass/fail, not just an observation. Then, while BGM is playing, manually raise
or lower the volume; let a video clip start and end, and confirm BGM resumes at your new
level, not the level from slideshow start. Manually change the volume again, then exit
the slideshow, and confirm the volume is left at your latest setting rather than snapped
back to the original session-start level.

---

## Definition of done

- [x] `ruff check`, `ruff format --check`, `mypy --strict`, `pytest` all clean —
  310 tests, 21 source files, zero warnings (2026-09-13)
- [x] Each user story's integration file passes on its own — `test_story1_playback.py`
  (50), `test_story2_video_clips.py` (33), `test_story3_configuration.py` (35), each
  runnable in isolation
- [x] Volume restored on every exit path, including the exceptional one — asserted in
  `test_fader.py` (`restore` invariant) and at the session level (`run()`'s
  `try`/`finally` teardown chain, exercised by a mid-fade-exception test)
- [x] Probe run completed and `tests/fakes/` reconciled against its log — T001 ran
  against real Kodi 21.3 (`tests/manual/kodi-probe-run.log`); the fakes were written
  directly from that log's D-001/D-005/D-013 findings, not built provisionally and
  reconciled after the fact
- [x] R-5 fully settled (2026-09-14, T041, real Kodi): `PlayMedia`'s `playoffset` is
  1-based, confirmed both by a real-device log and by Kodi's own source
  (`PlayerBuiltins.cpp`). It does **not** wrap past a playlist's end, and does not
  advance at all for `.pls`/`.xsp` — both found on real Kodi and fixed (research.md
  D-006's addendum and R-8): `resume_offset()` now wraps itself using
  `Playlist.Length(music)`, and `.pls`/`.xsp` are resolved to a concrete `bgm.m3u`
  before `playoffset` is ever used against them
- [x] R-6 settled: the clip-start fade has no full-volume burst — confirmed audibly on
  real Kodi across all four source formats, each a separate session with its own first
  clip's R-7 cold start (Tier 2 step 6 / T042, 2026-09-14)
- [x] R-2 fully settled: no volume OSD during fades (D-013), confirmed on real Kodi; a
  mid-session volume change survives the next fade and slideshow exit (FR-016, D-012),
  confirmed on real Kodi across all four source formats (Tier 2 step 7 / T043,
  2026-09-14)
- [x] Tier 2 steps 1-7 walked through on Kodi v20+ and all confirmed, including step 5
  (T041) across all four source formats (tasks.md T038-T043)
- [x] Log output matches [contracts/logging.md](./contracts/logging.md), header
  `[slideshow-BGM]` — enforced by `messages.py` being the sole `xbmc.log` call site,
  and pinned by test assertions against every required event's exact message shape
