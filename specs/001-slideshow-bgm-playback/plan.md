# Implementation Plan: Slideshow Background Music Playback

**Branch**: `001-slideshow-bgm-playback` | **Created**: 2026-09-09 | **Last revised**: 2026-09-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-slideshow-bgm-playback/spec.md`

## Summary

A Kodi Script Mode addon that plays background music for the duration of a slideshow,
gets out of the way when a slideshow video clip plays, and comes back afterwards.

This addon is built from scratch; no earlier implementation is carried forward. The
technical approach is shaped by three constraints identified in Phase 0 research (see
[research.md](./research.md)), each labelled there as an API fact, an inference, or an
unverified hypothesis:

1. **Kodi has one shared player.** A slideshow video clip takes it over and *destroys*
   the BGM stream. "Pause/resume" is therefore implemented as *stop → remember which
   track → replay* (D-001). The resume point is the **following** track, uniformly for
   every source, which removes any need to track elapsed playback time (D-004); the
   track index is read from `Playlist.Position(music)` in `onAVStarted` (D-005).
2. **Slideshow start/end emits no event.** Kodi's window transition produces no JSON-RPC
   notification, so liveness is sampled from an abort-aware `Monitor.waitForAbort(0.5)`
   loop — the narrow exception principle 1.2 allows (D-002).
3. **Volume is global, never per-player.** All four transitions fade over 1 s, but at a
   clip's start the only thing global volume can act on is the clip's own audio — the
   BGM stream is already gone — so that fade is a fade-*in* of the clip (D-003).

The addon is launched by an `<onload>` hook injected into the active skin's
`SlideShow.xml`, installed by a run-once script at the service extension point (D-007).

## Technical Context

**Language/Version**: Python 3.8 (floor set by Kodi v20 Nexus; no 3.9+ syntax such as
`dict |` merges, `list[str]` builtins generics at runtime, or `match`)

**Primary Dependencies**: Kodi Python API — `xbmc`, `xbmcgui`, `xbmcvfs`, `xbmcaddon`
(C++ bindings provided by Kodi at runtime; not pip-installable). No runtime third-party
dependencies. Dev-only: `pytest`, `Kodistubs`, `ruff`, `mypy`.

**Storage**: Kodi addon settings via `xbmcaddon` (`resources/settings.xml`); derived
`bgm.m3u` written to the addon profile directory
(`special://profile/addon_data/script.slideshow-bgm/`)

**Testing**: `pytest` against hand-written in-repo Kodi fakes (`tests/fakes/`) injected
into `sys.modules`; `Kodistubs` supplies annotations for `mypy --strict` (D-008).
Settings rendering and real callback ordering are verified manually in Kodi per the
constitution's Development Workflow, seeded by the `tools/kodi-probe/` run
(quickstart.md Tier 2 step 1).

**Target Platform**: Kodi v20 (Nexus) and above — Linux, Windows, macOS, Android

**Project Type**: Single project — Kodi Script Mode addon (standard Kodi addon layout)

**Performance Goals**: Every BGM transition completes within 2 s (SC-001, SC-002,
SC-003), of which the fade is 1000 ms and slideshow-end detection is up to 500 ms —
leaving ~500 ms of headroom for playback startup

**Constraints**: No persistent background service (principle 2.2); all background work in
daemon threads with explicit cleanup (2.1); no polling loop tighter than its documented
justification (1.1/1.2); `ruff check`, `ruff format --check`, `mypy --strict` all clean;
cyclomatic complexity ≤ 10 per function; captured global volume MUST be restored on every
exit path

**Scale/Scope**: One slideshow session at a time (Assumption 2); one BGM playlist; ~8
runtime modules; 3 user stories, 15 functional requirements

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Gate | Status |
|---|---|---|---|
| 1.1 | Event-driven, no polling loops | Track index via `onAVStarted`, not polling (D-005); playback transitions via Player callbacks | **PASS** |
| 1.2 | Longest workable wait interval | One justified sampler: session liveness at 0.5 s, the longest interval leaving headroom inside SC-003's 2 s (D-002). The position sampler was removed by D-004; track index is callback-driven (D-005) | **PASS with justification** |
| 2.1 | Daemon threads, explicit cleanup | The fade helper is the only daemon thread; joined on session teardown, volume restored in `finally` | **PASS** |
| 2.2 | No persistent service outside Script Mode | Skin-hookup script registers at the service extension point but exits immediately, holding no threads/timers/listeners | **PASS with justification** — see Complexity Tracking |
| 3.1 | Config only via `resources/settings.xml` | All five settings (`type`, `playlist`, `directory`, `random`, `on_existing_playback`) live in settings.xml; no custom config files | **PASS** |
| 4.1 | Key events logged to Kodi log | `[slideshow-BGM]`-prefixed logging for session start/end, BGM stop/replay, fades, and all errors (FR-009, D-010) | **PASS** |
| 5.1 | Kodi v20+ / Python 3.8+ | Targeting the 3.8 syntax floor; no API newer than v20 | **PASS** |
| 6.1 | Type annotations + Google docstrings | Enforced on every module boundary | **PASS** |
| 6.2 | ruff + mypy --strict, zero warnings, CI-blocking | `pyproject.toml` config + CI gate; Kodistubs makes `--strict` viable | **PASS** |
| 6.3 | Complexity ≤ 10 | Module split below keeps each unit small; `ruff` `C901` enforces | **PASS** |
| 6.4 | New dependency justified | Dev-only additions (pytest, Kodistubs, ruff, mypy); zero runtime dependencies | **PASS** |
| — | Testing Standards (NON-NEGOTIABLE) | TDD via tdd-agent; `/speckit-tasks` MUST emit test tasks for all three user stories | **PASS** |
| — | Security | No secrets involved; addon reads local media paths only | **PASS** |

**Post-Phase 1 re-check**: PASS, re-confirmed 2026-09-11. The module split in
[contracts/](./contracts/) keeps every unit inside the complexity ceiling, and the single
0.5 s Monitor wait (D-002) is the only non-callback-driven loop left — D-004 removed the
position sampler and D-005 made track identity callback-driven, so gate pressure went
down rather than up.

## Project Structure

### Documentation (this feature)

```text
specs/001-slideshow-bgm-playback/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── settings.md          # resources/settings.xml setting ids + semantics
│   ├── skin-integration.md  # SlideShow.xml onload hook contract
│   ├── modules.md           # Internal module/class interfaces
│   └── logging.md           # Kodi log line contract
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
addon.py                     # Script Mode entry point; owns the session lifecycle
service.py                   # Run-once skin hookup at profile login, then exits
addon.xml                    # Addon manifest (script + service extension points)

resources/
├── __init__.py
├── settings.xml             # All user configuration (principle 3.1)
├── language/
│   └── resource.language.en_gb/
│       └── strings.po       # Localized labels and messages
└── lib/
    ├── __init__.py          # addon singleton, addonId ("script.slideshow-bgm"), addonName ("Slideshow-BGM")
    ├── config.py            # Settings access + validation (FR-005..FR-008, FR-012, FR-014)
    ├── playlist.py          # Directory scan -> bgm.m3u, playlist validation (FR-006, FR-010, FR-012)
    ├── player.py            # BgmPlayer(xbmc.Player): callbacks, replay, resume (FR-001..FR-003)
    ├── fader.py             # Global-volume fade helper with baseline restore (FR-013)
    ├── session.py           # Monitor wait loop, session teardown (FR-004)
    ├── skinconnector.py     # SlideShow.xml onload hook install/remove (D-007)
    └── messages.py          # Notification/log wrappers (FR-009, FR-012)

tests/
├── conftest.py              # Injects Kodi fakes into sys.modules before import
├── fakes/                   # Behavioral Kodi doubles (single-player semantics, volume register)
├── unit/                    # Per-module tests
├── integration/             # User-story-level tests across modules
└── manual/
    └── slideshow-fixtures/  # Real media for Tier 2 manual testing (gitignored)
        ├── slideshow-source/  # Images + video clips — the slideshow's own target folder
        ├── bgm-source/         # The 10 mp3s (2 non-ASCII, D-009) also used as a directory BGM source
        └── playlists/          # my.m3u, my.pls, my.xsp — same 10 tracks, one per format

pyproject.toml               # ruff / mypy / pytest config (dev only, excluded from addon zip)
```

**Structure Decision**: Standard Kodi addon layout, which is non-negotiable for addon
repository acceptance — `addon.xml` at the root, user-facing code under `resources/lib/`,
settings at `resources/settings.xml`, localized strings under `resources/language/`. The
generic `src/models|services/` layout does not apply: Kodi loads `addon.py` and
`service.py` from the root by manifest reference. `tests/` and `pyproject.toml` sit at
the repo root and are excluded from the packaged addon.

The module split follows the seams the requirements already imply — configuration,
playlist construction, playback control, fading, session lifecycle, skin integration, and
user messaging — which also keeps each unit under the complexity ceiling (6.3).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| `service.py` registered at the `xbmc.service` extension point (principle 2.2 forbids services outside Script Mode) | A Script Mode addon cannot launch itself. The skin's `SlideShow.xml` must carry an `<onload>` hook, and installing that hook cannot be done by the Script Mode entry point — without the hook the script never runs, so it can never bootstrap. Profile login is the only reliable moment to (re)install it. The script inserts the tag and exits, holding no threads, timers, or listeners, so nothing persists. | A settings-screen action button alone leaves the addon silently broken whenever the user changes skins, with no feedback until a slideshow plays silently. Asking users to hand-edit a skin XML file is unacceptable for an addon distributed through the Kodi repository. |
| One sampling loop (principle 1.1 prefers callbacks) | Kodi emits no event for the slideshow window opening or closing (D-002), so liveness must be sampled. Principle 1.2 explicitly permits this where no event-driven alternative exists. | Pure callback-driven detection is impossible: `Monitor.onNotification` never fires for the slideshow window closing. Everything else that was previously sampled is now callback-driven or gone — track identity comes from `onAVStarted` (D-005) and the position sampler was removed entirely by D-004's next-track resume. One 0.5 s abort-aware Monitor wait is all that remains. |

## Spec amendments — applied

All amendments below are **carried in [spec.md](./spec.md)**; this section records what
changed and why. Two of the 2026-09-09 resolutions were reversed the following day after
the user reviewed Phase 0; the spec's Clarifications section marks the superseded
answers.

**2026-09-09**

1. **FR-013 / SC-002** — fades scoped to addon-initiated transitions only. *Superseded
   2026-09-10.*
2. **FR-003 / Assumption 6** — resume made format-dependent, with a sampled offset for
   `.m3u` and next-track for `.pls`/`.xsp`. *Superseded 2026-09-10.*
3. **FR-015 / Edge Case 5** — the spec was silent on skin integration (D-007), which
   FR-001 depends on entirely. FR-015 now requires it in user-facing terms, and Edge
   Case 5 records the skin-update hole (risk R-3). *Stands.*

**2026-09-10**

4. **FR-013 / SC-002 (supersedes 1)** — all four transitions fade over 1 s. At a clip's
   start the fade necessarily applies to the clip's *incoming* audio, since the BGM
   stream is already gone (D-003). The clip's audio is deliberately not faded out at its
   end, which would cost a sampler thread.
5. **FR-003 / Assumption 6 / US2 (supersedes 2)** — every source now resumes at the
   beginning of the **following** track (D-004). This removes the position sampler, the
   `seekTime()` call and its fallback, and all per-format branching; the remainder of an
   interrupted track is skipped. Risk R-1 is withdrawn as a result.
6. **Addon type — no spec change, decision recorded** — a service addon was considered
   as a way to avoid editing the skin and was rejected: it would poll for the whole Kodi
   session, put SC-001 out of reach, and require amending constitution principles 2.1
   and 2.2. The addon stays Script Mode with a skin hook. The rationale is written to be
   README-ready in [research.md](./research.md) D-007, "Why not a service addon".

**2026-09-12**

7. **FR-016 added (D-012, resolves R-2's correctness half)** — `baseline_volume` is
   re-captured from the current volume at every `PLAYING → SUSPENDED` transition, and
   once more before an end-of-session fade-out from `PLAYING`, instead of being captured
   once at slideshow start. Without this, a deliberate volume change the user made while
   BGM was playing was silently discarded by the next fade or by the slideshow-end
   restore.
8. **Fade mechanism changed, no requirement text affected (D-013, resolves R-2's
   remaining half)** — the fader now sets volume via the `SetVolume` builtin
   (`xbmc.executebuiltin`), not JSON-RPC (`xbmc.executeJSONRPC`). Checked against Kodi
   master source: JSON-RPC's `Application.SetVolume` shows Kodi's volume OSD
   unconditionally on every call with no way to suppress it, while the builtin only
   shows it when explicitly told to. Volume reads are unaffected and stay on JSON-RPC.
9. **Five wording fixes from `checklists/risk.md` review** — User Story 1's Independent
   Test now cites SC-001's 2-second bound instead of "shortly after"; FR-003 states that
   a single-track BGM playlist resumes into itself; FR-012 and Edge Case 2 now cover a
   directory BGM source becoming invalid at slideshow start, not only a playlist file
   (data-model.md's validation table already treated this generically — the fix brings
   spec.md's wording in line with the design, no design change); SC-004 states that a
   mid-slideshow setting change does not affect the session already in progress; FR-015
   now states that every resolution-variant file must be integrated, not just one
   (contracts/skin-integration.md already specified this — same kind of wording-only fix).

**Open before `/speckit-tasks` can be trusted**: nothing that changes a requirement,
provided the probe run confirms two things — R-5, that a track in a `.pls`/`.xsp`
playlist can be targeted (or FR-003's next-track clause is unreachable for those
formats), and R-6, that the clip-start callback arrives early enough to drop volume
before the clip is audible (or FR-013's clip-start clause has to go). Both are answered
by one run of `tools/kodi-probe/`; see quickstart.md Tier 2 step 1.
