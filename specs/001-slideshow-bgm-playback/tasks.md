---

description: "Task list template for feature implementation"
---

# Tasks: Slideshow Background Music Playback

**Input**: Design documents from `/specs/001-slideshow-bgm-playback/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md (all present)

**Tests**: Required, not optional — the project constitution's Testing Standards
(NON-NEGOTIABLE) override the tasks-template default: every user story and the
Foundational phase gets test tasks written before their implementation tasks, per the
tdd skill's red-green-refactor cycle.

**Organization**: Tasks are grouped by user story (spec.md P1/P2/P3) to enable
independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions (this feature)

Standard Kodi Script Mode addon layout (plan.md Project Structure), not a generic
`src/` layout — `addon.xml` at the repository root is what Kodi's addon manifest
requires:

```text
addon.py, service.py, addon.xml          # entry points + manifest (repo root)
resources/settings.xml                   # all user config (constitution 3.1)
resources/language/resource.language.en_gb/strings.po
resources/lib/                           # __init__, config, playlist, player, fader,
                                          # session, skinconnector, messages
tests/{fakes,unit,integration}/          # pytest + injected Kodi fakes (D-008)
pyproject.toml                           # ruff/mypy/pytest config, dev-only
```

---

## Phase 1: Setup

**Purpose**: Project initialization, tooling, and the one manual step that must start
as early as possible because everything else's test fakes depend on its output.

- [x] T001 [P] Run `tools/kodi-probe/` (see `tools/kodi-probe/README.md`) against a real
  Kodi v20+ instance and save the resulting `kodi.log`. This settles the **Hypothesis**
  items in research.md (D-001 callback identity, D-002 `Slideshow.*` condition names/
  timing — R-4, D-005 `Playlist.Position(music)` for `.pls`/`.xsp` — R-5, D-003 clip-
  start callback latency — R-6) with observed behavior instead of assumption. Has no
  code dependency — start this immediately, in parallel with everything else. T006's
  fakes are provisional until reconciled against this log (quickstart.md Tier 2 step 1).
  **Done 2026-09-13** — Kodi 21.3, both `.pls` and `.xsp` runs; log saved at
  `tests/manual/kodi-probe-run.log`; findings folded into research.md (D-001, D-002,
  D-003, D-005, R-4/R-5 resolved, R-6 refined, new R-7). T006's fakes still need to be
  reconciled against this log — not yet done.
- [x] T002 Create the addon project skeleton: `addon.xml` (script **and** service
  extension points, D-007), `resources/lib/`, `resources/language/resource.language.en_gb/`,
  `tests/{fakes,unit,integration}/` per plan.md Project Structure.
- [x] T003 [P] Configure `pyproject.toml`: `ruff` (lint + format + `C901` complexity ≤ 10
  plus the `D` pydocstyle rules, Google convention, to gate the Google-style-docstring
  requirement, constitution 6.1/6.2/6.3), `mypy --strict`, `pytest`, and dev-only
  dependencies (`Kodistubs`, `pytest`, `ruff`, `mypy` — zero runtime deps,
  constitution 6.4).
- [x] T004 [P] Add `.github/workflows/ci.yml` running `ruff check`, `ruff format --check`,
  `mypy --strict`, and `pytest` as a merge-blocking gate (constitution 6.2).
- [x] T005 Symlink the addon into a local Kodi installation
  (`ln -s "$PWD" ~/.kodi/addons/script.slideshow-bgm`) for the Tier 2 manual steps in
  Phase 6 (quickstart.md Setup).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The modules and test infrastructure every user story is built on —
`messages`, `fader`, `playlist`, `config`, `skinconnector`/`service`, and the session
skeleton (contracts/modules.md Dependency direction: `messages` is the only module
every other one imports; nothing user-story-specific lives here).

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Test infrastructure

- [x] T006 [P] `tests/fakes/xbmc.py`: a single shared `Player` that destroys audio
  playback when video starts and fires `onPlayBackStopped`/`onPlayBackEnded` (D-001);
  settable `Slideshow.IsActive`/`IsVideo`/`IsPaused` conditions (D-002);
  `Monitor.waitForAbort`; a settable `Playlist.Position(music)` infolabel returning
  `''` when nothing plays (D-005); a global volume register readable through a
  `GetProperties`-style fake and writable **only** through a `SetVolume`-builtin-style
  fake that records whether its optional OSD-show argument was ever passed (D-003,
  D-013) — **reconciled directly against T001's probe log** (not provisional):
  `start_video_clip()` fires `onPlayBackStopped` only, matching every clip transition
  observed; `getTime`/`getPlayingFile` raise `RuntimeError` once nothing plays,
  matching the log verbatim.
- [x] T007 [P] `tests/fakes/xbmcvfs.py`, `tests/fakes/xbmcgui.py`,
  `tests/fakes/xbmcaddon.py`: bytes-safe `exists`/`File`/`copy`/`listdir`;
  `Dialog().yesno`/`ok`/`notification` call recorders; `Addon()` settings getter/setter.
- [x] T008 `tests/conftest.py`: inject `tests/fakes/` into `sys.modules` before any
  `resources.lib` import (D-008) (depends on T006, T007). Verified with a throwaway
  smoke test (10 cases covering D-001/D-005/D-013 exactly, then removed) before
  handing the fakes to any test-writing work downstream.

### Tests for Foundational modules (write first, ensure they FAIL)

- [x] T009 [P] `tests/unit/test_messages.py`: `[slideshow-BGM] ` header on every log
  line, level routing per contracts/logging.md's table.
- [x] T010 [P] `tests/unit/test_fader.py`: `IN` always ramps 0→baseline, `OUT` always
  ramps current→0; the snap-to-0 runs synchronously inline (R-6); `restore()` fires on
  every exit path including an exception mid-fade (the invariant quickstart.md calls
  out by name); the `SetVolume`-builtin fake never receives a `showVolumeBar` argument
  from any fader call (R-2 regression guard, D-013).
- [x] T011 [P] `tests/unit/test_playlist.py`: a non-ASCII filename survives the bytes
  walk; all seven FR-006 extensions are collected; `bgm.m3u` regenerates only when
  absent or older than `settings.xml` (SC-004/SC-005).
- [x] T012 [P] `tests/unit/test_config.py`: the three validation checks run in order
  (contracts/settings.md); `Not Selected` is treated as unconfigured, not a path;
  `on_existing_playback` defaults to `TakeOver`.
- [x] T013 [P] `tests/unit/test_skinconnector.py`: `install` is idempotent (no
  duplicate `<onload>` on a second call); the `.original` backup is written once and
  never overwritten; every resolution-variant `SlideShow.xml` found is hooked, none
  skipped (FR-015); each of the four documented preconditions
  (not found/not readable/not writable/parse failure) logs its exact reason/remedy pair
  (contracts/skin-integration.md).

### Implementation for Foundational modules

- [x] T014 [P] `resources/lib/__init__.py`: `addon` singleton, `addon_id`
  (`"script.slideshow-bgm"`), `addon_name`, `profile_dir`.
- [x] T015 `resources/lib/messages.py`: `log()`/`notify()`/`ok()`/`yesno()`, every
  user-visible string looked up by id from `strings.po` (FR-009, FR-011, FR-012, D-010)
  (depends on T009, T014). Messages themselves arrive pre-resolved from callers; this
  module stays string-id-free by design (contract still upheld one layer up).
- [x] T016 [P] `resources/lib/fader.py`: `capture_baseline()` (JSON-RPC
  `Application.GetProperties` read), `fade()`/`restore()` (`SetVolume` builtin only,
  never JSON-RPC, no `showVolumeBar` argument — D-013), `cancel()` (FR-013, FR-016,
  D-003, D-012) (depends on T010, T014; no dependency on `messages` per
  contracts/modules.md's dependency graph, so this runs in parallel with T015). Also
  adds `join(timeout)` (not in the original contract signature list, needed by
  session.py's teardown per contracts/modules.md's own "join daemon threads with a
  timeout" prose — added as production API, not test-only).
- [x] T017 `resources/lib/playlist.py`: `scan_directory()` (bytes walk, FR-006
  extensions, case-insensitive), `write_m3u()`, `resolve()`, `needs_regeneration()`
  (FR-006, FR-010, D-009) (depends on T011, T015). `BgmSource.kind` is a `SourceKind`
  enum (`PLAYLIST`/`DIRECTORY`), matching data-model.md exactly.
- [x] T018 `resources/lib/config.py`: `read_source()`, `validate()`,
  `existing_playback_policy()` (FR-005–008, FR-011, FR-014) (depends on T012, T017).
  `prompt_until_valid()` is a bounded ask-once-then-decide, not an unbounded loop —
  Kodi gives an addon no way to re-open its own settings screen, so a literal loop
  could never terminate on its own; see the module docstring for the exact shape.
- [x] T019 [P] `resources/settings.xml`: `type` (FR-005), `playlist` (FR-007),
  `directory` (FR-006), `random` (FR-008), and `on_existing_playback` (FR-014)
  settings, with the D-011 `<dependencies>` grey-out block for `random` on
  `.pls`/`.xsp` (contracts/settings.md). D-011's block copied verbatim
  (source-verified operator set); the `playlist` extension mask is best-effort
  and explicitly flagged in an XML comment for Tier 2 step 3 (T039) to confirm
  against real Kodi, alongside the pre-existing case-sensitivity check.
- [x] T020 `resources/lib/skinconnector.py`: `find_slideshow_xml()` (every
  resolution-variant file, FR-015), `is_hooked()`/`install()`/`uninstall()` with
  backup-once semantics and the four-precondition failure path
  (contracts/skin-integration.md) (depends on T013, T015).
- [x] T021 `service.py`: `xbmc.service` entry point — resolve the active skin,
  `install()` into every file `find_slideshow_xml()` returns, exit immediately holding
  no threads (FR-015, D-007, constitution 2.2); on failure, one generic non-blocking
  notification via `messages.notify()` (depends on T020). Every candidate file is
  installed via a list comprehension (not a short-circuiting `all(generator)`) so one
  failure never skips the rest.
- [x] T022 `resources/lib/session.py` skeleton: `SlideshowSession` class,
  `is_slideshow_active()`, the `Monitor.waitForAbort(0.5)` loop shell (FR-004, D-002) —
  state transitions are filled in by US1/US2 below (depends on T015).

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 - Background Music Plays During a Slideshow (Priority: P1) 🎯 MVP

**Goal**: Background music starts automatically when a slideshow starts and stops when
it ends; with no source configured, the slideshow proceeds silently with no error.

**Independent Test**: Configure a BGM source, start an image-only slideshow, confirm
music starts within 2 seconds (SC-001) and stops when the slideshow ends.

### Tests for User Story 1 (write first, ensure they FAIL) ⚠️

- [x] T023 [P] [US1] `tests/integration/test_story1_playback.py`: valid source → player
  receives `PlayMedia` and volume ramps to baseline (FR-001, SC-001); slideshow goes
  inactive → fade out, stop, threads joined, volume restored to baseline (FR-004,
  SC-003); no source configured → no player call, no dialog, no exception (US1
  scenario 3, FR-010); a directory source that is missing or yields no supported audio
  at slideshow start triggers the same non-blocking notify+log path as a missing
  playlist file, since validation is kind-agnostic (FR-012). 50 cases; also added
  `tests/unit/test_player.py` (16 cases) for `Playlist.Position(music)` parse edges.

### Implementation for User Story 1

- [x] T024 [US1] `resources/lib/player.py`: `BgmPlayer(xbmc.Player)` with `start()`
  (`PlayMedia` + shuffle/repeat per FR-008, then fade in, D-006) and `onAVStarted()`
  recording `track_index` from `Playlist.Position(music)` (D-004, D-005) (depends on
  T023, T016). Exposes `self.position: BgmPosition` (public, `track_index`/`is_valid`,
  1-indexed exactly as Kodi reports it) for US2 to read verbatim.
- [x] T025 [US1] `session.py`: implement `STARTING → PLAYING → TERMINATED`
  (capture baseline, prime the source, `player.start()`; on exit: fade out, stop, join
  the fader thread, restore baseline) (FR-001, FR-004, FR-013) (depends on T024, T022).
  Teardown order is fade → **join** → stop (not fade → stop → join as originally
  drafted here): stopping before the ramp completes would cut the fade-out to silence
  instead of letting it finish audibly, which is what SC-003's "detection + full
  1-second fade-out" budget assumes.
- [x] T026 [US1] `addon.py`: Script Mode entry point — `config.read_source()` →
  construct `SlideshowSession` → `run()` (FR-001) (depends on T025, T018).
  `config.read_source()` is actually called from inside `session.py`'s `STARTING`
  handling, not `addon.py` itself, matching contracts/modules.md's dependency graph
  (`addon.py ──> session ──> config`) — `addon.py` only constructs and runs the session.
- [x] T027 [US1] Wire the FR-009 `session start`/`session end` log lines (exact message
  shapes per contracts/logging.md) into `session.py` (depends on T025).
- [x] T028 [US1] `STARTING → DISABLED` path: no source, unreadable source, or
  empty/invalid source — of either `BgmSource` kind, directory or playlist alike,
  since `resolve()`/`validate()` operate on the same abstracted path (data-model.md) —
  → `messages.notify`/`log`, slideshow proceeds silently (FR-010, FR-012, US1
  scenario 3) (depends on T025, T018). "Nothing configured at all" (scenario 3) logs
  only, with no notification, distinct from "configured but invalid at slideshow
  start" (FR-012), which does notify — matching spec.md's own wording distinction
  between the two cases.

**Checkpoint**: User Story 1 is fully functional and testable independently.

---

## Phase 4: User Story 2 - BGM Pauses and Resumes Around Video Clips (Priority: P2)

**Goal**: Background music pauses when a video clip starts and resumes at the
following track when the slideshow returns to an image; stays paused across
back-to-back clips.

**Independent Test**: Start a slideshow mixing images and at least one video clip;
confirm BGM pauses on clip start and resumes on clip end, independent of US3.

### Tests for User Story 2 (write first, ensure they FAIL) ⚠️

- [x] T029 [P] [US2] `tests/integration/test_story2_video_clips.py`: clip start →
  `SUSPENDED`, `track_index` frozen, volume dropped to 0 then the clip's own audio
  fades in (FR-002, FR-013); clip end with the next slide an image → resume at
  `track_index + 1` with fade-in (FR-003, SC-002); two clips back-to-back → stays
  `SUSPENDED` across both, exactly one suspend/one resume (US2 scenario 3, Edge
  Case 4); a single-track BGM playlist resumes into itself (FR-003); a clip ending at
  the same instant the slideshow exits produces no observable resume (FR-004
  precedence over FR-003). 33 cases; also extended `tests/unit/test_player.py` (+15).

### Implementation for User Story 2

- [x] T030 [US2] `player.py`: shared `onPlayBackStopped`/`onPlayBackEnded` handler
  gated on `Slideshow.IsVideo`; `resume_at()` targeting `track_index + 1`, falling back
  to `playoffset=0` when `is_valid` is `False` (FR-002, FR-003, D-001, D-004) (depends
  on T029, T024). The handler reports plain "clip started"/"clip ended" events via two
  `Callable[[], None]` constructor params rather than importing `session.py` (would
  close the dependency-graph cycle) — confirmed by grep, no `session` import in
  `player.py`. `onAVStarted` also gained a `Slideshow.IsVideo` guard: it fires for the
  slideshow's own clips too, and without the guard a clip's playback would clobber the
  frozen resume `track_index` and log a spurious `LOGWARNING`.
- [x] T031 [US2] Wire `fader` calls into `player.py`'s clip-start handler: re-capture
  `baseline_volume` (`capture_baseline()`) immediately before the inline snap-to-0,
  then fade the clip's incoming audio in (FR-013, FR-016, D-012, R-6 ordering hazard)
  (depends on T030, T016). Upgraded to a new `fader.effective_baseline()` (added
  directly, TDD, after this task landed): a plain `capture_baseline()` re-baseline can
  catch a transient mid-ramp value if a clip starts during the initial fade-in;
  `effective_baseline()` returns the in-flight ramp's own target in that case, falling
  back to `capture_baseline()` when idle. Also applied to `_teardown`'s pre-existing
  re-baseline call for the same reason (a slideshow exiting during the initial fade-in).
- [x] T032 [US2] `session.py`: add `PLAYING ↔ SUSPENDED` transitions to the state
  machine, including the re-baseline-before-teardown step when leaving `PLAYING`
  (FR-016) and the FR-004-over-FR-003 precedence when a clip end and slideshow exit
  coincide (depends on T031, T025). Also fixes a real US1-era bug: teardown now only
  calls `player.stop()` when `state is PLAYING` — while `SUSPENDED`, Kodi's one player
  *is* the slideshow's own video clip (D-001), and stopping it would cut the slideshow's
  content short on the way out (Edge Case 3).
- [x] T033 [US2] Wire the FR-009 suspend/resume/still-suspended log lines (contracts/
  logging.md) (depends on T032).

**Checkpoint**: User Stories 1 AND 2 both work independently.

---

## Phase 5: User Story 3 - User Configures the BGM Source (Priority: P3)

**Goal**: The user picks a directory or playlist file as the BGM source, with or
without shuffle, and controls whether an already-playing Kodi player is taken over.

**Independent Test**: Change the BGM source in settings (directory vs. playlist,
shuffle on/off), start a slideshow, confirm the music played matches.

### Tests for User Story 3 (write first, ensure they FAIL) ⚠️

- [x] T034 [P] [US3] `tests/integration/test_story3_configuration.py`: directory source
  → recursive scan builds the BGM playlist (scenario 1); each of `.m3u`/`.pls`/`.xsp`
  as source (scenario 2); shuffle honored for directory/`.m3u` (scenario 3); shuffle
  ignored for `.pls`/`.xsp` regardless of the setting (scenario 4); `TakeOver` stops
  existing playback and starts BGM vs. `Yield` leaves existing playback untouched and
  skips BGM (scenario 5). 35 cases; also found and closed a real FR-008 gap (see T035
  note) with +21 `test_playlist.py` / +13 `test_config.py` unit cases, red-confirmed by
  reverting the fix (exactly the 11 format/shuffle-dependent cases failed, nothing else).

### Implementation for User Story 3

- [x] T035 [US3] `config.py`: `prompt_until_valid()` — blocking `Dialog().yesno`
  re-selection loop, `Dialog().ok` "BGM disabled" notice on cancel (FR-011) (depends on
  T034, T018). **Already fully built and tested in the Foundational phase (T018)** —
  verified, not rebuilt. The real gap found here was different: FR-008/research.md
  D-011 require shuffle to be *ignored* at runtime for `.pls`/`.xsp` sources, and
  `read_source()` was passing the `random` setting through unconditionally. Fixed by
  adding `PlaylistFormat` (`M3U`/`PLS`/`XSP`, data-model.md) and a `BgmSource.
  supports_shuffle` derived property to `playlist.py`, and reconciling `shuffle`
  against it in `read_source()` — case-insensitive extension match, directory sources
  always `M3U` (shuffle honored, since what reaches `PlayMedia` is the derived
  `bgm.m3u` regardless of the directory's own name).
- [x] T036 [US3] `session.py` `STARTING` transition: apply
  `existing_playback_policy()` — `TakeOver` stops existing playback before starting
  BGM; `Yield` routes straight to `DISABLED` without touching existing playback
  (FR-014, US3 scenario 5) (depends on T034, T025). **Already fully built in User
  Story 1** (`_claim_the_player()`) — verified against a dedicated scenario-5
  integration test in T034's new file, not rebuilt.
- [x] T037 [US3] Route every FR-011/FR-012 user-facing string through a `strings.po`
  id — no hardcoded literals (contracts/modules.md `messages` contract) (depends on
  T028, T035, T036). **Already true** — verified by grep (no `xbmc.log`/`Dialog(`
  outside `messages.py`; every notify/ok/yesno call site resolves a `strings.po` id
  first) — nothing to add.

**Checkpoint**: All three user stories are independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Manual verification that automated tests cannot reach (constitution's
Development Workflow), plus the final quality gate.

- [x] T038 Tier 2 manual: skin hook install — confirm the `<onload>` element and the
  `.original` backup appear, exactly one `<onload>` survives a restart (idempotency), a
  skin switch gets re-hooked, and a read-only skin directory produces the documented
  `LOGERROR` reason/remedy pair plus one non-blocking notification, no crash
  (quickstart.md Tier 2 step 2). **Done 2026-09-13** against real Kodi 21.3
  (skin.arctic.horizon.2, skin.confluence, skin.estuary) — all four sub-items confirmed
  passing, after finding and fixing three real bugs along the way:
  1. `find_slideshow_xml()` never descended into a skin's resolution subdirectory
     (`1080i/`) — `xbmcvfs.exists`/`listdir` only recognize a directory with a trailing
     slash on its path (research.md D-009 addendum). Fixed in `skinconnector.py` and
     `config.py` (same quirk broke `DIRECTORY`-source validation); the fake now
     reproduces the quirk.
  2. The hook and `.original` backup were correct, but `diff` against the backup showed
     the rewrite had silently normalized the file's XML declaration style
     (`'1.0'`/`'utf-8'` → `"1.0"`/`"UTF-8"`) and dropped its trailing newline —
     contradicting `skinconnector.py`'s own "everything but the hook unchanged"
     contract. Fixed: `install`/`uninstall` now capture and reproduce the original
     declaration and trailing-newline presence. Confirmed via byte-clean `diff` (only
     the `<onload>` line added).
  3. **The serious one, found testing sub-item 4 (read-only skin, skin.estuary —
     package-installed under `/usr/share/kodi/`, root-owned)**: the log claimed
     `skin hook: installed` at `LOGINFO` and `install()` returned success, but
     **nothing was actually written** — confirmed live (`grep -c RunAddon(...)` was
     `0`, file mtime untouched since package install, no `.original` created either).
     Root cause: real `xbmcvfs.File.write()`/`copy()` return `False` on a permission
     failure instead of raising, and `_write()`/`_back_up()` only ever checked for an
     exception. Worse, `_is_writable()`'s precondition probe never called `write()` at
     all (open+close only), so it could not have caught this in principle. All three
     fixed (research.md D-009's second addendum has the full account); the fake's
     `File` class now reproduces the non-raising failure for `"w"`/`"a"` modes.
     Re-verified on skin.estuary: exact `LOGERROR` reason/remedy line, file still
     untouched, non-blocking notification shown, no crash.
- [x] T039 [P] **Needs the user, on real Kodi** — Tier 2 manual: settings UI —
  `playlist`/`directory` show/hide with `type`, file mask, defaults, localization, and
  the D-011 `random` grey-out including the uppercase-extension (`.PLS`) case
  (quickstart.md Tier 2 step 3).
  - **Two bugs found and fixed (2026-09-14)**, both source-verified against Kodi's own
    code (see research.md D-011 addenda): (1) the `playlist` file-browse dialog showed
    "0 items" for a folder that actually contained `.m3u`/`.pls`/`.xsp` files — the
    control used `format="path"` (`ShowAndGetDirectory()`, folder-only, ignores
    `<masking>`) instead of `format="file"` (`ShowAndGetFile()`, applies masking); (2)
    the `random` toggle was permanently greyed out regardless of `type` — two sibling
    `<dependency type="enable">` elements are ANDed by Kodi, not ORed, so the
    `Directory`-only and `Playlist`-only branches formed a mutually-exclusive,
    always-false condition; fixed by wrapping both branches in one `<or>`.
  - **A third bug found and fixed (2026-09-14)** in the same `random` dependency after
    re-testing bug (2): the `Playlist` branch's negated `!contains .pls`/`!contains .xsp`
    form left `random` wrongly enabled for `playlist=Not Selected` (contains neither
    substring) and for `my.PLS` (uppercase — Kodi's `contains` is case-sensitive with no
    case-insensitive form, source-verified). Fixed by flipping to a positive
    `contains .m3u` / `contains .M3U` match instead, which closes both failures at once
    and fails closed for anything not on the list. Full rationale in research.md D-011's
    addenda.
  - **Re-verified and confirmed (2026-09-14)**: `random` now enables correctly for
    `type=Directory` and for a qualifying `.m3u` `Playlist`, and stays disabled for
    `Not Selected`, `.pls`/`.xsp` (lowercase), and `.PLS`/`.XSP` (uppercase). File mask,
    type-spinner show/hide, defaults, and localization all confirmed working.
- [x] T040 [P] **Needs the user, on real Kodi** — Tier 2 manual: tail `kodi.log` during
  a mixed slideshow and confirm every line matches contracts/logging.md, with no
  missing `session end` line (quickstart.md Tier 2 step 4).
  - **Confirmed (2026-09-14)** against `~/.kodi/temp/kodi.log` from a real run over
    `tests/manual/slideshow-fixtures/` (`.m3u` source, mixed photo/video slideshow):
    all 11 `[slideshow-BGM]` lines matched contracts/logging.md's shapes exactly —
    `session start`, `BGM start: track=unknown` (expected: `PlayMedia` is async, so the
    first `onAVStarted` lands after this line, matching `_track_label`'s documented
    behavior), two suspend/resume pairs with correct track arithmetic, and exactly one
    `session end` reporting the restored volume. No `LOGWARNING`/`LOGERROR`. Extra
    `still suspended: next slide is a video clip` DEBUG lines around the first clip were
    cross-checked against Kodi's own log and traced to R-7's already-documented
    renderer cold-start reopen (a `CRenderManager::Configure - timeout waiting for
    configure` warning followed by a duplicate `Player.OnPlay` for the same clip a few
    ms later) — the addon's already-SUSPENDED no-op path absorbs it correctly; not a
    new bug.
- [x] T041 Tier 2 manual: track targeting across `.m3u`/`.pls`/`.xsp`/directory — a clip
  interrupting track N resumes at the beginning of track N+1 for every format
  (quickstart.md Tier 2 step 5, R-5), including whether Kodi's `PlayMedia playoffset` is
  itself 1-based (it is, confirmed both via a real-device log and via Kodi's own source,
  `PlayerBuiltins.cpp`).
  - **Confirmed on real Kodi (2026-09-14)**: all four source formats now advance
    correctly per clip and wrap from the last track back to the first, including an
    `.xsp` at Kodi's own default save location, picked the normal way through the
    addon's settings screen. Directory source additionally confirmed to alphabetize
    (not directory-scan order) and to regenerate `addon_data/bgm.m3u` correctly.
  - **Four real bugs found along the way, all fixed** (full detail and Kodi-source
    citations in research.md's D-006 addendum and R-8):
    1. **Wrap-around** (`.m3u`/`.pls`/directory): a `playoffset` past a playlist's end
       clamps to the last track in real Kodi instead of wrapping, disproving the
       `PlayerControl(RepeatAll)`-wraps-it assumption the original design relied on.
       Fixed: `resume_offset()` (`resources/lib/player.py`) now wraps itself, reading
       `Playlist.Length(music)` alongside the existing `Playlist.Position(music)` read.
    2. **`.pls`/`.xsp` never advance past track 1 at all** — a separate, more severe
       bug than 1, not merely a boundary case. Fixed by amending D-004: both formats
       are now resolved by the addon itself into a concrete track list and flattened
       into the same derived `bgm.m3u` a `DIRECTORY` source already used
       (`resources/lib/playlist.py`: `parse_pls()`/`resolve_xsp()`), so `playoffset`
       only ever runs against a plain `.m3u`. Shuffle stays disabled for both formats,
       unchanged (confirmed with the user beforehand).
    3. **`.xsp` JSON-RPC schema violation**: `resolve_xsp()` requested a `filetype`
       property that `Files.GetDirectory` doesn't accept as a request parameter (it's
       always present in the response regardless) — Kodi rejected the whole call.
       Fixed by dropping it from the request.
    4. **`.xsp` `Invalid params` for Kodi's own default save location**: an `.xsp`
       under `special://musicplaylists/`, picked via the addon's own settings dialog,
       still failed — `Files.GetDirectory` only accepts a few protocol roots or an
       already-registered source, and the dialog resolves `special://` down to a plain
       absolute path before the addon ever sees it. Fixed by
       `_prefer_special_musicplaylists()`, keyed off `special://profile/playlists/
       music/` rather than the more obvious `special://musicplaylists/` alias, since
       that alias turned out to resolve to a `multipath://` union of two real
       directories, not a single path a prefix rewrite could ever match against.
  - **One robustness improvement** (user-requested, not a bug): `parse_pls()` now
    drops any `File<N>=` entry whose resolved path doesn't actually exist
    (`xbmcvfs.exists`), so a stale `.pls` reference never reaches `bgm.m3u`.
  - **Coverage gap closed**: a real-device question the user raised (a `bgm.m3u` older
    than `settings.xml` that still wasn't updated) turned out to be bug 2 above
    manifesting as a silent-looking symptom — `_regenerate()` correctly never touches
    `bgm.m3u` when the new source itself fails to resolve, so the previous session's
    file is left exactly as it was rather than emptied. This was true all along but had
    no direct test; added
    `test_resolve_leaves_a_stale_m3u_untouched_when_regeneration_fails`.
  - 359 tests passing, `ruff`/`mypy` clean throughout.
- [x] T042 **Needs the user, on real Kodi** — Tier 2 manual: clip-start fade timing —
  the clip's audio fades in from silence with no full-volume burst before the dip
  (quickstart.md Tier 2 step 6, R-6). research.md's R-7 finding matters here
  specifically: watch the **first** video clip of a slideshow session, not just any
  clip — the probe measured a ~1.7 s renderer cold-start delay there versus ~0.2–0.4 s
  for every later clip, so the first clip is the one most likely to show a burst.
  - **Confirmed (2026-09-14)**: a first round sounded fine overall but without singling
    out the first clip specifically. A second, more thorough round then ran all four
    source formats (`.m3u`/`.pls`/`.xsp`/directory) as four separate sessions — each with
    its own first-clip cold start — and confirmed no sound-burst before the dip in any
    of them ("공통사항: 모두 clip의 sound burst 현상을 없었음").
- [x] T043 **Needs the user, on real Kodi** — Tier 2 manual: no volume OSD appears
  during any fade or the clip-start snap; a manual volume change mid-session survives
  the next fade and the slideshow exit (quickstart.md Tier 2 step 7, R-2/D-012/D-013).
  - **Confirmed (2026-09-14)**: no volume OSD confirmed in an earlier round; this round
    confirmed a manual mid-session volume change survives correctly across all four
    source formats ("수동 볼륨 변경 후 유지됨. 이상 없음").
- [x] T044 [P] Final quality gate: `ruff check`, `ruff format --check`,
  `mypy --strict`, `pytest` all clean with zero warnings (constitution 6.2). 359 tests
  passing (as of R-8's `.xsp`/`.pls` fixes), 21 source files, zero warnings across all
  four gates, confirmed on this run.
- [x] T045 Walk quickstart.md's Definition of Done checklist to completion — every item
  checked off, including T038–T043 on real Kodi (2026-09-14) and `tests/fakes/`
  reconciled against T001's probe log (the fakes were written directly against the
  probe log from the start, not provisional).

---

## Phase 7: Post-release enhancement (2026-09-15, user-requested)

**Purpose**: Two user-requested additions found via further ad-hoc real-Kodi testing
after Phase 6 closed — not a new user story, but real behavioral/UX gaps worth closing
under the same TDD/Tier-2 discipline as the rest of this project.

- [x] T046 TDD: reject a `.xsp` smart playlist whose root `<smartplaylist type="...">`
  is not `songs`/`music` (research.md R-8 addendum, 2026-09-15). A
  `movies`/`musicvideos`/`mixed` smart playlist can resolve to real, playable *video*
  files through `resolve_xsp`'s `Files.GetDirectory` call, which would otherwise slip
  into the derived `bgm.m3u` undetected. Added `playlist.is_music_smartplaylist()`
  (reads the `.xsp` XML directly, fails closed, self-logs the specific reason at
  LOGWARNING/LOGERROR); a new `config.Reason.NOT_MUSIC_PLAYLIST` and a 4th ordered
  `validate()` check between `MISSING` and `EMPTY`; `messages.notify()` gained an
  `icon` parameter so this one reason gets an error-styled notification (`#32005`)
  distinct from every other reason's generic `#32004` toast, per explicit user request.
  24 new tests (359 → 383), `ruff`/`mypy` clean throughout. **Confirmed on real Kodi
  (2026-09-15)**: a `type="movies"` `.xsp` logs the exact type found and disables BGM
  with the distinguishable error notification; a `type="songs"` `.xsp` is unaffected.
- [x] T047 Settings UI: surface the Music (Songs) requirement to the user
  (research.md D-011 addendum, 2026-09-15). First attempt — a standalone
  `type="string"`/`control type="label"` "notice" row, visible only when `type` is
  `Playlist` — rendered **nothing** on real Kodi; source-verified that
  `settings version="2"` has no working standalone-notice mechanism (`type="lsep"` is a
  version-1-only token; a generic label control isn't instantiated by the addon
  settings dialog at all). Fixed by folding the requirement into the `playlist`
  setting's existing `help="30021"` string instead, shown in the bottom info bar when
  that row has focus — which is hidden automatically whenever `type` is `Directory`,
  since the row itself already is. Also applied a `\n` line break (confirmed
  respected by Kodi's `GUITextLayout`) to `#30021`, `#30023`, `#32004`, and the new
  `#32005` for readability. **Confirmed on real Kodi (2026-09-15)**: the two-line help
  text renders correctly under `playlist` when focused.
- [x] T048 Harden every `xbmcvfs` write against the D-009 "returns False, never raises"
  convention, in the two places the standing rule was not applied (found by an
  adversarial review, 2026-09-15). `playlist.write_m3u()` now returns `bool`, writes
  through a `bgm.m3u.part` sibling, checks every `write()` result plus the finished
  byte size, and only then replaces the destination — so a partial write can no longer
  leave a truncated playlist carrying a *fresh* mtime that `needs_regeneration` would
  read as up-to-date and serve forever. `skinconnector._roll_back()` restores a skin's
  SlideShow.xml from its `.original` when `_write` fails (mode `"w"` truncates before
  writing), for both `install()` and `uninstall()`, logging restored / restore-failed /
  no-backup as three distinct `LOGERROR` lines. 383 → 406 tests.
- [x] T049 Differentiate derived-`bgm.m3u` invalidation by source kind
  (research.md D-009; the one rule was designed for directories and had been extended
  to `.pls`/`.xsp` by R-8 without revisiting it). `.xsp` now **always** rebuilds — a
  smart playlist is a live library query whose results change while its file does not,
  and re-running it is one indexed JSON-RPC call. `.pls` rebuilds when `bgm.m3u` is
  older than `settings.xml` *or* than the `.pls` itself (mtime, not a content hash: no
  new persisted artifact, and it reuses the mechanism already there). A source that
  cannot be stat'd never forces a rebuild — that would discard a cached playlist that
  still plays, in favor of a source that can no longer be read (FR-010). Directory
  behavior deliberately unchanged pending T050. 406 → 416 tests.
- [x] T050 Measure the directory `os.walk` cost that D-009's cache exists to avoid,
  before deciding whether to close the SC-005 gap (a directory whose contents changed
  without a settings change still serves a cached playlist). Synthetic nested
  Artist/Album trees, 5 runs each, on both filesystems present on the dev machine:
  **ext4** 2.6 / 5.0 / 25.8 / 51.8 / 102.9 ms and **fuseblk** 10.1 / 20.6 / 101.5 /
  205.5 / 411.8 ms for 500 / 1k / 5k / 10k / 20k tracks — linear, 5.1 µs and 20.6 µs
  per track respectively. Against SC-001's ~500 ms of headroom (2 s total, minus
  FR-013's 1 s fade and up to 0.5 s detection), a realistic few-thousand-track library
  costs ~100 ms even on the slow filesystem. Caveats: warm-cache only (dropping caches
  needs root), and network shares were not measured — though `scan_directory` uses
  `os.walk`, which cannot traverse an `smb://` URL at all, so a network directory
  source appears to be unsupported today regardless of caching (logged as an open
  question, not addressed here). A second pass then dropped the caches
  (`echo 3 > /proc/sys/vm/drop_caches`) and re-measured: **ext4** 19.4 / 37.1 / 49.0 /
  57.9 / 116.3 ms and **fuseblk** 20.9 / 41.6 / 220.7 / 430.9 / 865.1 ms at the same
  five scales — a flat ~2.1× cold penalty on fuseblk, and on ext4 only a fixed ~17 ms
  of filesystem warm-up that stops mattering as the tree grows. **Decision: remove the
  cache** (T052) — the single over-budget cell (20k tracks, fuseblk, cold) is one the
  cache never fixed anyway, since the first slideshow after any settings change pays
  the identical cold walk.
- [x] T051 Remove the unreachable FR-011 blocking-dialog cluster and amend the spec to
  match (found 2026-09-15 while looking for a trigger for T046's `.xsp` check).
  `config.prompt_until_valid()` had **zero production call sites**: a Script Mode addon
  has no process running while its settings screen is open, and Kodi offers no callback
  for a changed `path` setting, so the moment FR-011 describes cannot be reached.
  Removed `prompt_until_valid`, `_valid_source`, `messages.ok`, `messages.yesno`,
  strings `#32002`/`#32003`, and the 10 tests covering them (their CJK coverage was
  retargeted at `notify`). `tests/fakes/xbmcgui.py` keeps its blocking-dialog surface —
  the fake mirrors Kodi's API, and the "no dialog was raised" assertions stay as
  regression guards. Amended spec.md (FR-011, Edge Case 1, a 2026-09-15 Clarifications
  entry), research.md D-010, contracts/settings.md, contracts/modules.md,
  data-model.md, quickstart.md and plan.md. 416 → 406 tests.
- [x] T052 Remove the derived-`bgm.m3u` mtime cache; re-resolve every derived source on
  every slideshow start (decision from T050's measurements; research.md D-009's third
  addendum carries the full rationale). Closes the SC-005 gap: a directory whose
  contents change without a settings change no longer serves a stale playlist, and a
  `.xsp` — a live library query — is no longer cached at all. `needs_regeneration`,
  `_is_newer_than` and `_uses_derived_m3u` deleted; `_resolve_derived` always
  regenerates. Two things keep that cheap and observable: `_regenerate` skips the write
  entirely when the resolved track list matches what `bgm.m3u` already holds (direct
  content comparison, deliberately not a stored hash — exact, and no new persisted
  artifact), and it logs the resolver's elapsed milliseconds with the track count at
  `LOGDEBUG`, so a genuinely slow real-world setup shows up in `kodi.log` rather than
  being guessed at. The now-unreachable `_has_content` re-check in `_resolve_derived`
  was dropped with it, and contracts/logging.md gained the new `LOGDEBUG` line's shape.
  406 → 395 tests (19 obsolete cache tests removed, 2 of them inverted into their
  opposites — a track added to the directory now *does* appear next start, citing
  SC-005 — plus 8 new ones covering re-resolution, the skipped rewrite, an mtime-
  preserving `.pls` edit, and the duration logging). Known residual limit, recorded not
  hidden: a very large library on slow storage can still exceed SC-001 on a cold walk —
  not a regression, since the cache never prevented that case either.
- [x] T053 Close the fader cancellation race with a generation counter under the lock
  (research.md D-003's 2026-09-15 addendum; design refined by the project owner).
  `_ramp` checked a cancellation `Event` and wrote the volume as two separate steps, so
  a step could clear the check and then land *after* a newer `fade()` or after
  `restore()` — at teardown that left the user's global volume permanently attenuated,
  violating D-003's invariant. Reachable by simply exiting a slideshow during a clip's
  fade-in, where `_teardown` skips both the fade-out and the `join()`. Every transition
  now claims a generation under `_lock`, and each ramp step re-checks it **inside the
  same critical section as its write**; `fade(IN)`'s inline snap is part of that claim
  (while still running on the calling thread for R-6), `fade(OUT)` re-validates after
  its JSON-RPC baseline read, `restore()` is self-invalidating so callers need not
  `cancel()` first, and `join()` waits on every tracked worker outside the lock on one
  overall deadline (deliberately without invalidating — teardown relies on `join()`
  letting the fade-out finish audibly for SC-003). The `Event` survives only as a
  wake-up optimization. 395 → 403 tests, `fader.py` at 100% statement coverage; the
  race tests are deterministic (workers parked at the exact gap via a substituted lock
  and write, never `sleep()`), and 5 of the 8 fail against the pristine module — the
  teardown one showing a 4% write landing after `restore(70)`. Suite run 10× plus the
  fader file 20× sequentially and 6× in parallel with no flakes.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001 (the probe) can start immediately and
  run in the background throughout; T002–T005 can start immediately.
- **Foundational (Phase 2)**: Depends on Setup (T002 skeleton) — BLOCKS all user
  stories.
- **User Stories (Phase 3+)**: All depend on Foundational completion.
  - US1 (P1) has no dependency on US2/US3.
  - US2 (P2) extends `player.py`/`session.py` files US1 created, so build it after
    US1 even though its spec scenarios are independent.
  - US3 (P3) extends `config.py`/`session.py` similarly — after US1, independent of
    US2's content.
- **Polish (Phase 6)**: Depends on all three user stories being complete.

### Within Each Phase

- Tests MUST be written and FAIL before their corresponding implementation task
  (constitution Testing Standards, NON-NEGOTIABLE).
- Within Foundational: `messages` (T015) and `fader` (T016) have no dependency on each
  other and can run in parallel; `playlist` (T017) depends on `messages`; `config`
  (T018) depends on `playlist`; `skinconnector` (T020) depends on `messages`;
  `service.py` (T021) depends on `skinconnector`; `session.py` skeleton (T022) depends
  on `messages`.
- Within US1/US2/US3: implementation tasks are sequential within the story (each
  edits `player.py` or `session.py` incrementally) — only the test task at the start
  of each story is `[P]`.

### Parallel Opportunities

- T001 (probe) runs alongside literally everything else in Setup/Foundational/US1–3.
- T003, T004 (Setup) are parallel to each other and to T001.
- T006, T007 (fakes) are parallel to each other.
- T009–T013 (Foundational tests) are parallel to each other.
- T014, T016, T019 (Foundational implementation) are parallel to each other and to
  the rest of Foundational's sequential chain where noted above.
- The single test task that opens each user story phase (T023, T029, T034) has no
  same-phase sibling to be `[P]` with, but is independent of the other two stories'
  test tasks.
- T039, T040, T044 (Polish) are parallel to each other; the rest of Polish is
  sequential/manual.

---

## Parallel Example: Foundational

```bash
# Launch independent Foundational tests together:
Task: "tests/unit/test_messages.py"
Task: "tests/unit/test_fader.py"
Task: "tests/unit/test_playlist.py"
Task: "tests/unit/test_config.py"
Task: "tests/unit/test_skinconnector.py"

# Launch independent Foundational implementation together:
Task: "resources/lib/__init__.py"
Task: "resources/lib/fader.py"      # no dependency on messages.py
Task: "resources/settings.xml"      # pure XML, independent of config.py's code
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (start T001's probe immediately; it runs in the background).
2. Complete Phase 2: Foundational — CRITICAL, blocks every story.
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: run `test_story1_playback.py`, confirm SC-001/SC-003
   independently of US2/US3.
5. Demo: a slideshow with no video clips and no settings UI beyond a hardcoded source.

### Incremental Delivery

1. Setup + Foundational → foundation ready (probe reconciled against fakes).
2. Add US1 → test independently → MVP.
3. Add US2 → test independently → BGM now safe to use with video clips.
4. Add US3 → test independently → users can actually change the source without
   editing code.
5. Phase 6 Polish → manual Tier 2 gate + final quality check before merge.

---

## Notes

- `[P]` tasks = different files, no dependency on incomplete work.
- `[Story]` label maps a task to its user story for traceability.
- Tests are mandatory here (constitution override) — write them first, watch them
  fail, then implement.
- The probe (T001) and the Tier 2 manual steps (T038–T043) need a real Kodi instance;
  they cannot be run by an automated agent — flag them for the user to execute.
- Commit after each task or logical group.
- Avoid: vague tasks, same-file conflicts inside a single phase, cross-story
  dependencies that break independent testability.
