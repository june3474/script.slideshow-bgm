# Implementation Plan: Skin Integration Consent

**Branch**: `002-skin-hook-consent` (spec directory only — work is on `main`) | **Date**: 2026-09-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-skin-hook-consent/spec.md`

## Summary

At profile login the run-once service currently installs the `<onload>` hook into every
`SlideShow.xml` of the active skin without asking (001/D-007, FR-015). This feature puts a
consent step between *finding* those files and *modifying* them: each file is first
**assessed read-only** into one of three states, and only if at least one needs the hook is
the user shown **one** blocking Yes/No dialog. Yes runs the existing install unchanged; No
or Back/Esc leaves the skin untouched and the addon dormant, to be asked again at the next
login. Nothing is persisted — the hook's presence in the skin *is* the consent record.

The approach is shaped by three constraints from Phase 0 ([research.md](./research.md)),
each labelled there as an API fact, an inference, or an unverified hypothesis:

1. **A Kodi-level disable would make the re-ask impossible.** Kodi starts only *enabled*
   addons' services at launch, so "No = disabled" would silence the very question the user
   asked to see again. "No" is a *soft* disable: the addon stays enabled, the skin stays
   unhooked, and nothing launches the addon (D-016, API fact).
2. **A file the user cannot act on must not be asked about.** Read-only skins would
   otherwise face a question that cannot succeed on every login. That forces the
   read-only *assess* step to run **before** the dialog and to share its checks with
   `install()`, so the two can never disagree (D-017).
3. **The dialog is a single `yesno`, and on Estuary its body auto-scrolls rather than
   fitting.** That is an unverified readability risk to retire on a real device (R-9).
   To keep the body short it does **not** print the injected line: it says in words what
   is added and points to README.md's section "2. Skin integration" for the exact code
   (D-018, 2026-09-22).

The reversal of 001's "no blocking dialog at login" stance is deliberate and scoped to the
consent question only — see D-015.

## Technical Context

**Language/Version**: Python 3.8 (floor set by Kodi v20 Nexus; no 3.9+ syntax) — unchanged
from 001.

**Primary Dependencies**: Kodi Python API — `xbmcgui.Dialog.yesno`, plus the `xbmc`,
`xbmcvfs`, `xbmcaddon` surface 001 already uses. No new runtime or dev dependency.

**Storage**: None. No consent flag, setting or file is written (FR-007). Localised text is
added to the four existing `strings.po` files.

**Testing**: `pytest` against the in-repo fakes (D-008). The `xbmcgui` fake already
records `yesno` calls and returns a settable answer, so no fake change is needed for the
happy paths. Dialog readability and startup behaviour are Tier 2 (manual, real Kodi).

**Target Platform**: Kodi v20 (Nexus) and above — Linux, Windows, macOS, Android.

**Project Type**: Single project — Kodi addon (unchanged).

**Performance Goals**: None. Runs once per profile login and is bounded by the user's
answer time; the assess step reuses probes 001 already performs on every login.

**Constraints**: Constitution 2.2 — after `service.main()` returns, no thread, timer or
listener may remain; the dialog is a synchronous call, so this holds. `ruff check`, `ruff
format --check`, `mypy --strict` clean; cyclomatic complexity ≤ 10 per function, which is
why the orchestration is split into helpers rather than growing `main()`.

**Scale/Scope**: 3 modules changed (`skinconnector`, `messages`, `service`), 4 string
files, 1 new integration test file plus additions to 2 unit-test files; 3 user stories,
12 functional requirements, 7 success criteria.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Gate | Status |
|---|---|---|---|
| 1.1 | Event-driven, no polling loops | No loop of any kind is added; the dialog is a blocking call that returns on the user's answer | **PASS** |
| 1.2 | Longest workable wait interval | No wait interval introduced | **PASS** |
| 2.1 | Daemon threads, explicit cleanup | No thread introduced | **PASS** |
| 2.2 | No persistent service outside Script Mode | `service.py` still exits when `main()` returns, holding no thread/timer/listener. The dialog only lengthens the run to the user's answer time; 001's Complexity Tracking justification for the service extension point is unchanged | **PASS** |
| 3.1 | Config only via `resources/settings.xml` | No new configuration — deliberately no "pre-approve" or "don't ask again" setting (spec Assumptions) | **PASS** |
| 4.1 | Key events logged to Kodi log | Consent requested / granted / declined-or-dismissed are each logged (FR-010, contract) | **PASS** |
| 5.1 | Kodi v20+ / Python 3.8+ | `Dialog.yesno(heading, message)` is the long-stable two-argument form; the newer `defaultbutton` argument is not used | **PASS** |
| 6.1 | Type annotations + Google docstrings | Enforced on every new function, including private helpers | **PASS** |
| 6.2 | ruff + mypy --strict, zero warnings | Same gates as 001 | **PASS** |
| 6.3 | Complexity ≤ 10 | `service.main()` splits into assess / consent / install helpers; `install()` is refactored onto a shared inspection routine rather than duplicated | **PASS** |
| 6.4 | New dependency justified | None added | **PASS** |
| — | Testing Standards (NON-NEGOTIABLE) | TDD via tdd-agent; `/speckit-tasks` MUST emit test tasks for all three user stories | **PASS** |
| — | Security | No secrets. The feature *improves* the security posture: a third-party file is no longer modified without the user knowing | **PASS** |

**Post-Phase 1 re-check**: PASS, 2026-09-21. The design adds no thread, no persisted state
and no dependency; the one constitution-adjacent question — a blocking dialog in the
login service — is a *behavioural* reversal of a 001 decision (D-015), not a violation of
principle 2.2, which restricts persistent background work rather than dialogs.

## Project Structure

### Documentation (this feature)

```text
specs/002-skin-hook-consent/
├── plan.md                  # This file (/speckit-plan command output)
├── research.md              # Phase 0 output — D-015..D-018, R-9..R-11
├── data-model.md            # Phase 1 output — file states, consent request, run flow
├── quickstart.md            # Phase 1 output — Tier 1 gates + Tier 2 manual scenarios
├── contracts/
│   └── consent-dialog.md    # Phase 1 output — dialog, strings, log events, module API
├── checklists/
│   └── requirements.md      # Spec quality checklist (/speckit-specify)
└── tasks.md                 # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

Decision and risk numbers **continue 001's sequence** (D-015…, R-9…) rather than
restarting, because source docstrings cite them bare ("D-007"); a second D-007 would make
every such citation ambiguous.

### Source Code (repository root)

```text
service.py                        # MODIFIED — assess → consent → install orchestration
resources/lib/
├── skinconnector.py              # MODIFIED — assess(), SlideshowFileState;
│                                 #   install() refactored onto a shared inspection step
└── messages.py                   # MODIFIED — confirm(): the blocking Yes/No wrapper
resources/language/
└── resource.language.{en_gb,ko_kr,es_es,fr_fr}/strings.po
                                  # MODIFIED ×4 — #32006 heading, #32007 body

tests/
├── unit/test_skinconnector.py    # MODIFIED — assess()
├── unit/test_messages.py         # MODIFIED — confirm()
├── unit/test_strings.py          # NEW — id parity, no leftover placeholder, README pointer
└── integration/test_consent_flow.py
                                  # NEW — US1/US2/US3 through service.main() against a
                                  #   real temporary skin directory
```

**Structure Decision**: No new module. The three seams the feature needs already exist —
`skinconnector` owns "what is in the skin file", `messages` is the only module allowed to
construct an `xbmcgui.Dialog`, and `service.py` owns the run-level policy ("one toast per
run", 001 modules contract). The consent question is a run-level policy decision, so it
lives in `service.py`; the fact it needs (file state) comes from `skinconnector`, and the
dialog itself goes through `messages`. Dependency direction is
unchanged: `service ──> skinconnector ──> messages` and `service ──> messages`.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations. The one thing a reader might mistake for one — a blocking dialog raised
from the login service, which 001 explicitly decided against — is a change of *policy*
recorded and justified as D-015, not a breach of any constitution principle.

## Spec amendments — applied

**2026-09-21**

1. **Consent scope (spec Clarifications)** — "No" is a soft disable, consent is never
   persisted, already-integrated skins get no dialog, and unmodifiable files are excluded
   from the question. All four are recorded in [spec.md](./spec.md).
2. **Dialog shape (D-018)** — a single `yesno`, chosen over "text viewer, then `yesno`"
   by the project owner on 2026-09-21 because the spec's one-dialog wording (FR-008,
   SC-005) is worth keeping. **Confirmed final on 2026-09-22**: the text viewer and a
   custom window are both set aside, and the wording of #32007 was condensed instead
   (English 542 → 364 characters). If Tier 2 still finds the body unreadable (R-9), the
   remedy is further shortening or reopening the decision, not a fallback layout.
3. **001/FR-015 and the 2026-09-11 clarification** — partially superseded for the consent
   question only; [001's spec.md](../001-slideshow-bgm-playback/spec.md) carries a
   pointer. The 001 contracts (`skin-integration.md`, `modules.md`, `logging.md`) and
   `messages.py`'s "deliberately no blocking-dialog wrapper" wording are updated with the
   implementation, not before — they describe code that does not exist yet.

**2026-09-22**

4. **The injected line leaves the dialog (project-owner decision)** — showing the
   143-character line was most of what made the body slow to read, so the dialog now says
   in words that integration code is added and points to README.md's section "2. Skin
   integration". FR-002(b) was rewritten; **FR-003 and SC-006** (shown line = written
   line) were withdrawn; `skinconnector.hook_line()` and the helper behind it were removed
   as dead code; the "harmless in nearly all cases" reassurance moved to the README, whose
   section 2 now also explains the guard condition.

**Observation, out of scope**: 001's `install()` checks writability *before* checking
whether the hook is already present, so a skin file that is already hooked but read-only
reports an install failure on every login. This feature keeps that order, because
changing it would alter 001 behaviour that this spec says is otherwise untouched. It is
worth a separate decision.
