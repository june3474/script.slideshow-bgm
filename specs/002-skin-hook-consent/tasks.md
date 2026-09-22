---

description: "Task list for the skin integration consent dialog"
---

# Tasks: Skin Integration Consent

**Input**: Design documents from `/specs/002-skin-hook-consent/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/consent-dialog.md, quickstart.md (all present)

**Tests**: Required, not optional — the project constitution's Testing Standards
(NON-NEGOTIABLE) override the tasks-template default. Every test task below is written
first and MUST be seen to fail for the stated reason before the implementation task that
follows it; each test-then-implementation pair is one red-green cycle of the tdd skill,
executed via the tdd-agent per the constitution.

**Organization**: Grouped by user story (spec.md P1/P1/P2). Unlike 001, the stories here
are not fully parallel: the ask-and-install orchestration in `service.py` is built in US1
(T014), and US2 and US3 pin down behaviours of that same flow, so they follow it. Their
*test criteria* are still independent (see each phase's Independent Test).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1, US2 or US3 (spec.md)
- Every task names its exact file paths

## Path Conventions (this feature)

Standard Kodi addon layout, as in 001 (plan.md Project Structure). No new module:

```text
service.py                                   # orchestration (MODIFIED)
resources/lib/skinconnector.py               # assess(), state enum (MODIFIED)
resources/lib/messages.py                    # confirm() (MODIFIED)
resources/language/resource.language.{en_gb,ko_kr,es_es,fr_fr}/strings.po   # +#32006 #32007
tests/unit/{test_skinconnector,test_messages,test_strings}.py
tests/integration/test_consent_flow.py       # NEW
```

---

## Phase 1: Setup

**Purpose**: Prove the baseline is green, because Phase 2 refactors existing, shipped code.

- [X] T001 Run the four gates from the repository root — `ruff check .`, `ruff format --check .`, `mypy --strict .`, `pytest` — and confirm all pass before any change. Note the passing test count (405 at the start of this feature) at the end of this task. T006 refactors `install()`; that refactor is only provably safe against a suite known to be green beforehand.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The three primitives every story needs — the single source for the injected
line, the read-only file assessment that shares its checks with `install()`, and the
blocking Yes/No wrapper. No user story can start before these exist.

**⚠️ CRITICAL**: T002–T004 first (red), then T005–T007.

### Tests (write first, watch them fail)

- [X] T002 [P] In `tests/unit/test_skinconnector.py` add tests for `skinconnector.hook_line()`: (a) it equals the module-level `HOOK` literal already defined at the top of that file; (b) after `skinconnector.install(path)` on a plain SlideShow.xml, the file's text contains `hook_line()` verbatim (FR-003, SC-006). *Break named*: the dialog's line and the written line being maintained in two places and drifting. **Superseded 2026-09-22 by T028**: `hook_line()` and these two tests were removed.
- [X] T003 [P] In `tests/unit/test_messages.py` add tests for `messages.confirm(heading, message)`. Monkeypatch `xbmcgui.Dialog.yesno` with a spy that records `(args, kwargs)` and returns a configurable value. Assert: returns `True` when the dialog returns `True`; returns `False` when it returns `False`; heading and message reach the dialog unchanged as the only two arguments, with **no** keyword arguments — in particular no `autoclose` (FR-009). *Break named*: adding an `autoclose` timeout, which would silently turn "no answer" into "No".
- [X] T004 In `tests/unit/test_skinconnector.py` (after T002 — same file) add tests for `skinconnector.assess(path)` and the `SlideshowFileState` enum (`INTEGRATED`, `NEEDS_INTEGRATION`, `NOT_MODIFIABLE`; values `"integrated"`, `"needs_integration"`, `"not_modifiable"`). Reuse the file's helpers (`_write_xml`, `PLAIN_XML`, `HOOKED_XML`, `_failure_line`, `restore_permissions`). One test per branch of data-model.md's assessment order: plain file → `NEEDS_INTEGRATION`; hooked file → `INTEGRATED`, and logs `skin hook: already present (<path>)` at `LOGDEBUG`; hooked with a hand-edited condition → `INTEGRATED`; missing file, unreadable file, read-only file, read-only directory, malformed XML, and root-not-`<window>` → each `NOT_MODIFIABLE`. Parametrise the seven failing kinds (adding "not valid UTF-8") and assert `assess` logs the exact reason and remedy contracts/skin-integration.md names; the existing `install` tests pin `install` to the same literals, so the two cannot disagree (D-017). For a needs-integration, an integrated and a not-modifiable file assert `assess()` left the file byte-identical and the directory holding only `SlideShow.xml` — no `.original`, no `.slideshow-bgm-write-probe`. *Break named*: `assess()` growing its own copy of the checks and diverging from `install()`, or writing before consent.

### Implementation

- [X] T005 In `resources/lib/skinconnector.py` add `_hook_element()` (builds the `<onload condition=HOOK_CONDITION>HOOK_TEXT</onload>` element, no tail) and `hook_line()` (returns `ElementTree.tostring(_hook_element(), encoding="unicode")`), and change `_append_hook` to append `_hook_element()` and then set its `.tail = "\n"`. Google-style docstrings (constitution 6.1). Makes T002 green; the existing `install` tests must stay green. **Superseded 2026-09-22 by T028**: `_hook_element()` and `hook_line()` were removed and `_append_hook` restored to its original form.
- [X] T006 In `resources/lib/skinconnector.py` add `SlideshowFileState` (`enum.Enum`) and a shared `_inspect(path)` that runs, in this fixed order and stopping at the first hit, exactly what `install()` runs today — `_preconditions_ok` (found → readable → writable), read, `_parse_content` — returning the content and parsed root (or `None` when the file cannot be modified) so nothing is read twice; a small `_hook_present(root, path)` helper shares the "already present" check and its `LOGDEBUG` line `skin hook: already present (<path>)`. Failures log via the existing `_log_failure`. Add public `assess(path) -> SlideshowFileState` on top of them, and **refactor `install()` onto `_inspect`** without changing its behaviour, order of checks, log lines or return values (D-017). *(Implemented as `Optional[_Inspected]` rather than a state tuple — same sharing, simpler typing.)* Keep every function at cyclomatic complexity ≤ 10. Refactor rule: the whole existing `tests/unit/test_skinconnector.py` suite passes before (T001) and after. Makes T004 green.
- [X] T007 [P] In `resources/lib/messages.py` add `confirm(heading: str, message: str) -> bool` returning `bool(xbmcgui.Dialog().yesno(heading, message))` with Google-style docstring, and update the module docstring's "There is deliberately no blocking-dialog wrapper" paragraph to say `confirm` exists for the one consent question (research.md D-015) and every other surface stays non-blocking. Makes T003 green.

**Checkpoint**: `ruff`, `mypy --strict` and `pytest` green. `assess()` classifies files without writing, `install()` is unchanged in behaviour, and `confirm()` exists.

---

## Phase 3: User Story 1 - Understand and Approve the Skin Change (Priority: P1) 🎯 MVP

**Goal**: Before any skin file is modified the user sees one Yes/No dialog that says what
will change and where to read the details; Yes runs the existing install.

**Independent Test**: With a writable skin whose SlideShow.xml lacks the hook and the fake
dialog set to Yes, `service.main()` shows the dialog once — with the file still
byte-identical and no backup yet — then hooks the file and creates its `.original`.

### Tests for User Story 1 (write first, watch them fail)

- [X] T008 [P] [US1] Create `tests/unit/test_strings.py`. Parse each `resources/language/resource.language.<lang>/strings.po` (`msgctxt "#<id>"` → `msgid`, `msgstr`). Assert: all four languages define exactly the same id set; ids 32006 and 32007 exist in each; for `ko_kr`, `es_es`, `fr_fr` both new `msgstr` values are non-empty and their `msgid` equals the `en_gb` text; the displayed body (`en_gb` `msgid`, otherwise `msgstr`) of #32007 contains exactly one `{0}`, on a line of its own, and `.format("X")` does not raise; each language's body still contains the literal `SlideShow.xml` (FR-012, SC-007). *Break named*: a translator dropping or duplicating the placeholder, or a language missing the ids so users see a raw string id.
- [X] T009 [P] [US1] Create `tests/integration/test_consent_flow.py` with the shared fixtures and the US1 tests. Fixtures: a `skin_root` fixture mirroring `tests/unit/test_skinconnector.py` (`monkeypatch.setitem(xbmcvfs.SPECIAL_ROOTS, "skin", ...)`); an autouse fixture loading the **real English text** of ids 32001, 32006 and 32007 from `resources/language/resource.language.en_gb/strings.po` into `xbmcaddon.store.localized_strings`; a `yesno` spy (monkeypatch `xbmcgui.Dialog.yesno`) that records `(heading, message)` and, **at the moment it is called**, snapshots every SlideShow.xml's bytes and the skin directory listing, then returns a configurable answer; and a `_run_service()` helper calling `import service; service.main()`. US1 tests: (1) for a skin lacking the hook the dialog is shown exactly once and, at that moment, the file is byte-identical and no `.original` or probe file exists (FR-001, SC-001); (2) the dialog message equals the English #32007 text formatted with `skinconnector.hook_line()`, and the heading equals English #32006 (FR-002, FR-003); (3) answering Yes leaves exactly one `RunAddon(script.slideshow-bgm)` in the file, an `.original` byte-equal to the pre-run file, exactly one each of the log lines `skin hook: consent requested for 1 file(s)`, `skin hook: consent granted` and `skin hook: installed (<path>)`, and no failure toast (FR-004, FR-010). *Break named*: installing (or backing up) before asking; building the message from anything but the real string. *(2026-09-22, T028: the body has no placeholder any more, so test (2) now asserts the message equals the shipped English #32007 unformatted.)*

### Implementation for User Story 1

- [X] T010 [P] [US1] Add ids #32006 (heading) and #32007 (body) to `resources/language/resource.language.en_gb/strings.po` under the existing "# Addon-facing messages" block, with the `msgid` text **verbatim from** `contracts/consent-dialog.md` and `msgstr ""`, matching the file's existing entry style.
- [X] T011 [P] [US1] Add the same two ids to `resources/language/resource.language.ko_kr/strings.po`: `msgid` the English source, `msgstr` a Korean translation conveying all four statements of the contract in order, with `{0}` left untouched on its own line.
- [X] T012 [P] [US1] Same for `resources/language/resource.language.es_es/strings.po` (Spanish). Flag it for native-speaker review in the commit message; a review may improve wording but must not drop a statement.
- [X] T013 [P] [US1] Same for `resources/language/resource.language.fr_fr/strings.po` (French), flagged for native-speaker review in the commit message.
- [X] T014 [US1] Rewrite the flow in `service.py` per data-model.md's Run flow, in small helpers (each ≤ 10 complexity, Google docstrings, `List`/`Tuple` from `typing` for the 3.8 floor). Add `STRING_CONSENT_HEADING = 32006` and `STRING_CONSENT_BODY = 32007`. `_assess_all(paths) -> Tuple[List[str], bool]` calls `skinconnector.assess` once per path and returns the `NEEDS_INTEGRATION` paths plus whether any file was `NOT_MODIFIABLE`. `_ask_consent(pending) -> bool` logs `skin hook: consent requested for <n> file(s)`, calls `messages.confirm(heading, body.format(skinconnector.hook_line()))` with both strings from `addon.getLocalizedString`, and on `True` logs `skin hook: consent granted`. `_install_all(pending) -> bool` uses a list comprehension so **every** pending file is attempted even if one fails (001/FR-015). `main()`: the no-files-found path is unchanged; otherwise assess, then — only if something is pending and consent was given — install; show exactly one non-blocking failure toast if any file was `NOT_MODIFIABLE` or any install failed. Update the module docstring: still holds no thread, timer or listener (constitution 2.2); the dialog is a synchronous call. Makes T008 and T009 green. *(2026-09-22, T028: the body is passed to `messages.confirm` unformatted — the `.format(skinconnector.hook_line())` is gone.)*

**Checkpoint**: US1 works end to end — a user shown the dialog can approve, and the skin is modified only after they do. Do not ship on this alone; see Implementation Strategy.

---

## Phase 4: User Story 2 - Decline Without Side Effects (Priority: P1)

**Goal**: No, or Back/Esc, changes nothing, keeps the addon enabled, and returns at the
next login.

**Independent Test**: With a skin lacking the hook and the fake dialog set to `False`, run
`service.main()` twice: the skin directory is identical after each run, nothing was
installed, the addon was never disabled, and the dialog appeared both times.

### Tests for User Story 2 (write first, watch them fail)

- [X] T015 [US2] In `tests/integration/test_consent_flow.py` (after T009 — same file) add: (1) answering No leaves the SlideShow.xml byte-identical, the skin directory listing unchanged (no `.original`, no `.slideshow-bgm-write-probe`), `skinconnector.install` never called (spy), exactly one log line `skin hook: consent declined or dismissed — skin left untouched; will ask again at next profile load`, and no `consent granted` line (FR-005, SC-002); a comment on this test records that Back/Esc is indistinguishable from No because `yesno` returns `False` for both (research.md D-018); (2) the addon is never disabled — spy `xbmc.executeJSONRPC` and `xbmc.executebuiltin` and assert no call mentions `SetAddonEnabled`, `DisableAddon` or `EnableAddon` (D-016); (3) running `service.main()` twice after No shows the dialog twice, leaves the file unhooked and logs the declined line twice (FR-005, SC-004); (4) the dialog is invoked with no keyword arguments, i.e. no timeout (FR-009). *Break named*: backing up before asking; disabling the addon on No; remembering the answer; adding an `autoclose`.

### Implementation for User Story 2

- [X] T016 [US2] In `service.py`'s `_ask_consent` (T014) add the declined branch: on `False` log `skin hook: consent declined or dismissed — skin left untouched; will ask again at next profile load` at `LOGINFO` via `messages.log`, so each of the three outcomes is logged exactly once per run (FR-010). Do not disable the addon and write no state (D-016, FR-007). Makes T015 green.

**Checkpoint**: US1 and US2 together are the shippable consent feature.

---

## Phase 5: User Story 3 - No Interruption Where No Consent Is Needed (Priority: P2)

**Goal**: Ask only when a modification is actually needed, once per login, and again only
when the hook has gone missing.

**Independent Test**: An integrated skin yields zero dialogs and zero file changes;
removing the hook, or switching to an unintegrated skin, yields exactly one dialog.

### Tests for User Story 3 (write first)

- [X] T017 [US3] In `tests/integration/test_consent_flow.py` (after T015 — same file) add, each seeding files with the helpers used above: (1) every file `INTEGRATED` (`HOOKED_XML`, and a hand-edited-condition variant) → zero dialogs, bytes identical, no consent log lines, no toast, `install` not called (FR-006, SC-003); (2) Yes, then overwrite the file with the plain XML and run again → the dialog appears again; then repoint `xbmcvfs.SPECIAL_ROOTS["skin"]` at a second unintegrated skin → dialog again; and after each run `xbmcaddon.store.settings` is unchanged and nothing was written under the fake profile directory (FR-007); (3) skin with `1080i/`, `720p/` and `16x9/` copies all pending → exactly one dialog, its consent log says `3 file(s)`; Yes hooks and backs up all three, No touches none (FR-008, SC-005); (4) one `INTEGRATED` plus one pending file → one dialog; No leaves both byte-identical; Yes modifies only the pending one and creates no `.original` for the integrated one; (5) only a read-only pending file (`restore_permissions`) → no dialog, exactly one failure toast (#32001) and the `LOGERROR` reason line; a writable pending file plus a read-only one → one dialog, Yes installs the writable one only, one toast; the same mix answered No → nothing changes, still one toast (Edge Case 2, FR-011); (6) no SlideShow.xml found at all → no dialog, the not-found log and one toast, exactly as in 001; (7) a `yesno` spy that makes the pending file read-only *before* returning Yes → `install` fails at write time, exactly one failure toast, no exception, the file neither truncated nor modified (D-017: `install` re-inspects). *Breaks named*: asking once per file rather than per run; asking about an integrated or unmodifiable file; trusting the pre-dialog assessment instead of re-inspecting.
- [X] T018 [US3] These behaviours largely fall out of T006 and T014, so their tests may pass on first run. For each such test in T017, prove it guards something: temporarily introduce its named break in `service.py` / `skinconnector.py` (ask per file; skip the `INTEGRATED` filter; include `NOT_MODIFIABLE` files in the question; skip the re-inspection in `install`), confirm the test fails for the stated reason, and revert. Leave the named break as a one-line comment above each test. If any T017 test fails without a deliberate break, fix the cause in `service.py` (T014's helpers) — no other production change is expected in this phase. **Done 2026-09-21** — 15 deliberate breaks (7 against the US1/US2 behaviour, 8 against US3's), each reverted afterwards, and every one failed at least one test: install before asking; No treated as Yes; a Kodi-level disable on No; a remembered decline; a different line shown than written; the request never logged; an `autoclose` added; one question per file; integrated files asked about; unmodifiable files asked about; `install` skipping re-inspection; consent persisted in a setting; unmodifiable files not reported; a hand-edited hook counted as missing; asking even when nothing is pending. No production change was needed in this phase.

**Checkpoint**: All three stories work and are pinned by tests.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Bring the 001 design record in line with the code (contracts/consent-dialog.md
lists exactly what to change), and close out verification.

- [X] T019 [P] Update `specs/001-slideshow-bgm-playback/contracts/skin-integration.md`: change the Lifecycle table's "Profile login / Kodi start" row to assess → consent → install, and amend the paragraph saying neither failure surface is a blocking dialog so it says the consent question is the one blocking exception, with a link to `../../002-skin-hook-consent/contracts/consent-dialog.md`.
- [X] T020 [P] Update `specs/001-slideshow-bgm-playback/contracts/modules.md`: add `assess`, `hook_line` and `SlideshowFileState` to the `skinconnector` block; add `confirm` to the `messages` block and replace the "There is deliberately no blocking-dialog wrapper" paragraph with the 002 wording; update the `service.py` entry-point docstring and the note under Dependency direction that `service.py` reaches `messages` directly for the consent dialog as well as the failure notification. *(`hook_line` was listed here and removed again by T028.)*
- [X] T021 [P] Update `specs/001-slideshow-bgm-playback/contracts/logging.md`: add the three consent events to the Required events table, with the exact message shapes from `specs/002-skin-hook-consent/contracts/consent-dialog.md`.
- [X] T022 [P] Add short pointers to 002 in `specs/001-slideshow-bgm-playback/research.md` under D-007 (login-time hook installation now asks first — 002/D-015) and D-010 (the surface inventory gains one blocking dialog, for consent only), each as a dated addendum in the file's existing style.
- [X] T023 [P] Update `CLAUDE.md`: add a row to the Symptom → document map for skin-hook consent (dialog shown or not shown, its wording, what No/Back does) pointing to `specs/002-skin-hook-consent/research.md` D-015..D-018 and R-9..R-11, and mention `specs/002-skin-hook-consent/` beside `specs/001-...` in the design-record convention bullet.
- [X] T024 [P] Update `README.md`: wherever it describes the skin integration, state that the addon asks before modifying the skin, what the dialog shows, what **No** does (nothing changes, the addon stays inactive, the question returns next login) and that disabling or uninstalling the addon stops the question. If the README has no such section, add a short "Skin integration and consent" subsection rather than scattering the text.
- [X] T025 Run the four gates from the repository root — `ruff check .`, `ruff format --check .`, `mypy --strict .`, `pytest` — zero warnings. Compare the passing test count to T001's and confirm the increase equals the tests added by T002–T004, T008, T009, T015 and T017, with no earlier test modified. **Done 2026-09-21** — 464 passed = 405 + 59 (T002–T004: 20, T008: 17, T009: 4, T015: 4, T017: 14); `git diff --numstat` shows the two existing test files gained lines and lost only one (the widened `typing` import).
- [X] T026 **Owner-run on a real Kodi — not runnable by an agent.** Execute quickstart.md's Tier 2 steps 1–14 and add a dated addendum to `specs/002-skin-hook-consent/research.md` recording the outcome per risk: R-9 (step 2), R-10 (steps 1 and 13), R-11 (step 3). A failure triggers that risk's stated remedy — for R-9, shortening the #32007 wording further or reopening D-018 with the evidence (the text viewer and a custom window were set aside by the project owner on 2026-09-22) — and a follow-up task here. Also update `tasks.md` if the outcome changes planned work, per CLAUDE.md's Tier 2 workflow. **Done 2026-09-22.** Two findings, not the risks anticipated: (1) the dialog body never localized (title did) on Korean and Spanish — root-caused and fixed as T029; (2) on Arctic Horizon 2 and Arctic Fuse 2 (not Estuary), the dialog blocks the skin's own boot sequence, halts it permanently after an answer, and neither button gets default focus — R-10 falsified for those skins, tracked as new R-12, root cause not yet confirmed (needs `kodi.log` from the affected run before a fix is designed). R-9 (Estuary) and R-11 both passed as hypothesized. Follow-up: T030.
- [X] T029 **Added 2026-09-22, Tier 2 finding (D-019).** Fix: the consent body (#32007) always displayed in English regardless of Kodi's UI language, even though its heading (#32006) localized correctly. Root-caused via `xbmc/guilib/LocalizeStrings.cpp`: Kodi always reloads `en_gb` after the active language and, per id, compares the reloaded `msgid` against the `msgid` a translated file stored as its own reference copy of the source text; on a mismatch it discards the translation and shows the English `msgid` instead (logged as `POParser: id:<n> was recently re-used in the English string file...`). `#32007`'s `en_gb` `msgid` had been hand-edited (dropping a `\n` before "However") without the same edit reaching `ko_kr`/`es_es`/`fr_fr`'s copies of that `msgid` — an escaped-quotes theory was considered and cleared via `POUtils.cpp::GetString`, which only checks a line's first/last character, not escapes in between. TDD: added `test_every_languages_msgid_matches_the_english_source_byte_for_byte` to `tests/unit/test_strings.py` (red: caught the existing #32007 mismatch; every other id already matched) and re-synced the three translated files' `msgid` to `en_gb`'s current text — `msgstr`, the actual translation shown, is untouched. Documented as research.md D-019. 468 passed; gates clean.
- [X] T030 **Root cause confirmed 2026-09-22 (Arctic Fuse 2 `kodi.log`), research.md R-12.** Arctic Fuse 2's own splash screen (`Custom_1198_Window_Startup.xml`) schedules a timed transition to Home (`AlarmClock` "splashtimeout" → `ActivateWindow(10000)`); that transition fired while our consent dialog (window `10100`) was open, and Kodi's window manager (`GUIWindowManager.cpp`) dropped it outright — logged as `Activate of window '10000' refused because there are active modal dialogs` — with no retry, ever. The user waited ~3 minutes with no GUI activity before quitting Kodi. Not Arctic-specific in mechanism: any skin with a timed splash-to-Home (or similar) transition races our dialog, whose open duration is unbounded (FR-009). "No button focus" from the original report is not fully explained by this log (Enter *was* routed to window 10100 and handled as Select); a texture not yet generated by the skin's own `script.texturemaker` run is a plausible but unconfirmed explanation.
- [X] T031 **Implemented 2026-09-22, research.md R-12.** Added `service.py`'s `_wait_for_home()`: before `_assess_all`'s pending files are asked about — never when there is nothing pending — wait (abort-aware, `xbmc.Monitor().waitForAbort(0.5)`, matching D-002's pattern; `WAIT_INTERVAL_SECONDS`/`HOME_WAIT_MAX_SECONDS`/`HOME_ACTIVE_CONDITION` module constants) for `xbmc.getCondVisibility('Window.IsActive(home)')`, capped at 10 s (20 iterations) so a skin with no reachable Home state is still asked, logging a `LOGWARNING` when the cap is hit. Constitution 1.2/2.2 checked: 0.5 s reuses D-002's own interval; the wait is a plain loop inside `main()`'s call stack, so nothing persists past it. TDD: added a `home_already_active` autouse fixture to `tests/integration/test_consent_flow.py` so every pre-existing test takes the fast path, plus 5 new tests (skip with nothing pending; skip when Home is already active; give up after exactly 20 calls and log when it never activates, dialog still shown; stop after exactly 1 call on Kodi's own abort). All 5 written red first against the unmodified `service.py`, confirmed failing for the missing-feature reason, then made green. 5 deliberate mutations (drop the wait; shrink the cap; ignore abort; wait with nothing pending; drop the log line) each caught by this set and reverted — the "wait with nothing pending" mutation was caught only after adding the test for it, closing a real gap the mutation pass found. 472 passed; `ruff`/`ruff format --check`/`mypy --strict` clean. Docs updated: research.md R-12, contracts/consent-dialog.md, quickstart.md steps 1 and 8. **Confirmed on real Kodi, 2026-09-22**: quickstart.md Tier 2 steps 1 and 8 re-run on both Arctic Fuse 2 and Arctic Horizon 2 — PASS on both (no block, no halt after answering). R-12 is closed.
- [X] T032 **Added 2026-09-22 (project-owner request), research.md D-020.** Default focus of the consent dialog is now **Yes**, overriding Kodi's own default of No (`CGUIDialogYesNo::Reset()`, `m_defaultButtonId = CONTROL_NO_BUTTON`). `messages.confirm()` now passes `defaultbutton=xbmcgui.DLG_YESNO_YES_BTN`; the constant (source-confirmed `CONTROL_YES_BUTTON = 11` via `SWIG_CONSTANT2` in `Dialog.h`, base values in `GUIDialogBoxBase.h`) was added to `tests/fakes/xbmcgui.py` alongside `DLG_YESNO_NO_BTN = 10`. TDD: `test_confirm_defaults_focus_to_yes` in `tests/unit/test_messages.py` (a `yesno` spy asserting the `defaultbutton` kwarg), red first (`None == 11`) against the unmodified `confirm()`, then green. Two deliberate mutations (swap to `DLG_YESNO_NO_BTN`; drop the kwarg entirely) both caught and reverted. Documented as independent of R-12's separate, unconfirmed "no visible focus indicator" observation — this changes *which* button defaults focused, not whether a focus indicator renders. 473 passed; gates clean. Docs updated: research.md D-020, contracts/consent-dialog.md.
- [X] T027 **Added 2026-09-22 (project-owner decision)**: condense the consent body #32007 in `resources/language/resource.language.{en_gb,ko_kr,es_es,fr_fr}/strings.po` into shorter full sentences (English 542 → 427 characters; the last English edit was the project owner's, dropping the "why it is harmless" clause, so FR-002(b) was relaxed to match, and its grammar was then tidied — `However,`, `No`) and keep the single `yesno` — no text viewer, no custom window, no link (research.md D-018). A data-only change: the existing `tests/unit/test_strings.py` (one placeholder on its own line, the file name present, non-empty in every language) and `tests/integration/test_consent_flow.py` (which reads the shipped English text) already guard its structure, and no test pins the new wording, since that would only detect that it changed. Documents updated with it: spec.md (Clarifications 2026-09-22, FR-002(b), User Story 1 scenario 2), plan.md, research.md (D-015, D-018, R-9), contracts/consent-dialog.md, quickstart.md, README.md and T026 above. es/fr remain drafts for native-speaker review.
- [X] T028 **Added 2026-09-22 (project-owner decision)**: take the injected line out of the consent dialog. The body #32007 now says in words that integration code is added to the current skin's `SlideShow.xml` so that the addon can run automatically when a slideshow starts, and points to README.md's section "2. Skin integration" (English 542 → 364 characters). Test-first: `tests/unit/test_strings.py` replaced the "one placeholder" test with "no leftover placeholder", "points to README.md and section 2" (each language) and "the README has that heading"; `tests/integration/test_consent_flow.py` now expects the shipped body unformatted — all red against the old strings, green after the four `.po` files changed. Then, as dead code: removed `skinconnector.hook_line()` and `_hook_element()` (restoring `_append_hook`) and the two tests that covered them, and dropped the `.format(...)` from `service.py`'s `_ask_consent`. README.md section 2 gained the guard-condition explanation the dialog no longer carries. **Spec**: FR-002(b) rewritten, **FR-003 and SC-006 withdrawn**, User Story 1 scenario 2, the Integration Line entity and an Assumption updated; Clarifications 2026-09-22. Also updated: plan.md, research.md (D-018, R-9), data-model.md, contracts/consent-dialog.md, quickstart.md, and 001's `skin-integration.md` and `modules.md`. Result: 467 passed; `ruff`, `ruff format --check` and `mypy --strict` clean. es/fr remain drafts for native-speaker review.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after T001. Blocks every story. Inside it, T002/T003 are red tests in different files; T004 waits for T002 (same file); T005 follows T002; T006 follows T004 and T005; T007 follows T003.
- **US1 (Phase 3)**: after Phase 2. T008 and T009 in parallel; T010–T013 in parallel; T014 needs T006, T007, T009 and T010.
- **US2 (Phase 4)**: after T014 (it pins the decline branch of T014's flow). T015 follows T009 (same file); T016 follows T014.
- **US3 (Phase 5)**: after T014 and T016. T017 follows T015 (same file); T018 follows T017.
- **Polish (Phase 6)**: after US1–US3. T019–T024 are different files and independent; T025 follows all code and doc tasks; T026 follows T025 and needs a real Kodi.

### User Story Dependencies

- **US1 (P1)**: no dependency on other stories; delivers the flow the others exercise.
- **US2 (P1)**: needs US1's flow to exist; independently *testable* by its own criteria.
- **US3 (P2)**: needs US1's flow; adds no production code of its own beyond fixes.

### Parallel Opportunities

- Phase 2 tests: T002 ‖ T003.
- US1 tests: T008 ‖ T009. US1 strings: T010 ‖ T011 ‖ T012 ‖ T013.
- Polish docs: T019 ‖ T020 ‖ T021 ‖ T022 ‖ T023 ‖ T024.

## Parallel Example: Phase 2 and User Story 1

```text
# Phase 2 — red tests together (different files):
Task: "T002 hook_line() tests in tests/unit/test_skinconnector.py"
Task: "T003 confirm() tests in tests/unit/test_messages.py"

# US1 — red tests together, then the four string files together:
Task: "T008 string parity tests in tests/unit/test_strings.py"
Task: "T009 US1 consent-flow tests in tests/integration/test_consent_flow.py"
Task: "T010 en_gb strings.po"   Task: "T011 ko_kr strings.po"
Task: "T012 es_es strings.po"   Task: "T013 fr_fr strings.po"
```

## Implementation Strategy

### MVP First

1. Phase 1, then Phase 2 (primitives and the `install()` refactor).
2. Phase 3 — US1: dialog, strings, Yes path. **Validate independently.**
3. Phase 4 — US2. **Ship US1 and US2 together**: a consent prompt whose No path is untested
   or unlogged is not consent, so US1 alone is a milestone, not a release.
4. Phase 5 — US3 pins when the question is and is not asked.
5. Phase 6, then the owner-run Tier 2 (T026) before merging, as the constitution's
   Development Workflow requires for behaviour that cannot be unit-tested.

### Incremental Delivery

Each phase leaves the gates green and the working tree committable. Commit per red-green
pair or logical group, on `main` (no feature branch — spec Clarifications 2026-09-21).
Pushing is left to the project owner.

## Notes

- Decision and risk numbers (D-015…, R-9…) continue 001's sequence; cite them bare in
  docstrings as 001's are cited.
- Do not change 001's ordering of `install()`'s checks (writability before hook presence):
  see the out-of-scope observation in plan.md and research.md D-017.
- A version bump is release management and is not part of this feature.
- Avoid: vague tasks, two tasks editing the same file in parallel, and any production
  change that has no failing test asking for it.
