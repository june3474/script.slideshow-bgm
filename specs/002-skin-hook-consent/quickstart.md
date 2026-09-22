# Phase 1 Quickstart: Validation Guide

**Branch**: `002-skin-hook-consent` | **Created**: 2026-09-21

How to prove this feature works. Same two tiers as
[001's quickstart](../001-slideshow-bgm-playback/quickstart.md), and the same rule: **green
Tier 1 tests do not close this feature**. Tier 2 is where R-9, R-10 and R-11
([research.md](./research.md)) are actually retired.

## Prerequisites

| Need | For |
|---|---|
| Everything in 001's quickstart Prerequisites | Tier 1 and Tier 2 |
| A skin whose `SlideShow.xml` is **writable** (a skin installed under `~/.kodi/addons/`) | Tier 2, US1/US2/US3 |
| A skin whose `SlideShow.xml` is **read-only** (a system-installed skin, e.g. under `/usr/share/kodi/addons/`) | Tier 2, Edge Case 2 |
| A skin that ships several resolution variants of `SlideShow.xml` | Tier 2, US3 sc. 4 |
| Kodi's UI language switchable to Korean, Spanish and French | Tier 2, SC-007 |

## Tier 1 — automated

### Quality gates (constitution 6.2, CI-blocking, zero warnings)

```bash
ruff check .
ruff format --check .
mypy --strict .
pytest
```

### What the tests must pin down

| Behaviour | Where | Requirement |
|---|---|---|
| `assess()` returns `INTEGRATED` / `NEEDS_INTEGRATION` / `NOT_MODIFIABLE` for hooked, plain, unreadable, read-only and malformed files — and writes nothing | `tests/unit/test_skinconnector.py` | FR-001, FR-006 |
| `assess()` logs exactly the reason and remedy `install()` would for an unmodifiable file | same | FR-011 |
| `install()` behaves exactly as before the refactor onto the shared inspection step | the existing `test_skinconnector.py` suite, unmodified and still green | FR-004 |
| `confirm()` returns `True` only for Yes; passes no `autoclose`; heading and message reach the dialog unchanged | `tests/unit/test_messages.py` | FR-001, FR-009 |
| All four `strings.po` files define the same ids; #32007 has no leftover `{…}` placeholder, names `SlideShow.xml`, and points to README.md's "2. Skin integration" in every language; the README still has that heading | `tests/unit/test_strings.py` | FR-002, FR-012, SC-007 |
| Dialog shown before any file changes; Yes installs all pending; No and dialog-dismissed change nothing and create no backup | `tests/integration/test_consent_flow.py` | US1, US2, FR-001, FR-005 |
| One dialog for several pending files; none for an integrated skin; none when every candidate is unmodifiable | same | US3, FR-006, FR-008 |
| A second run after No asks again; a second run after Yes does not | same | FR-005, FR-007, SC-003, SC-004 |
| Failure toast still fires, still non-blocking, alongside a consent answer | same | FR-011 |
| Consent requested / granted / declined each logged once | same | FR-010 |
| A skin file made read-only *while the dialog is open* is caught at write time, not trusted from the earlier assessment | same | D-017 |

### What the fakes already model

`tests/fakes/xbmcgui.py` records every `yesno` call and returns a settable answer, and
`tests/fakes/xbmcvfs.py` works against a real temporary skin directory. No fake change is
expected; if one turns out to be needed, the test that needed it says so.

---

## Tier 2 — manual in Kodi

Run with the addon symlinked into `~/.kodi/addons/` and Kodi restarted, as in 001.

| # | Do this | Expect | Retires |
|---|---|---|---|
| 1 | Writable skin, hook absent. Restart Kodi | The dialog appears over the home screen, is modal, and Kodi's startup is not stalled | R-10, R-12, US1 sc. 1 — **PASS on Estuary; originally FAILED on Arctic Horizon 2/Fuse 2 (2026-09-22), root-caused and fixed the same day (`_wait_for_home`); re-run confirmed PASS on both Arctic skins (2026-09-22). R-12 closed** |
| 2 | Read the whole dialog on Estuary, and on a second skin if available | All four statements — including the README pointer — are legible, by auto-scroll where needed, before answering. Check Spanish and French too: they are the longest | R-9, US1 sc. 2 — **PASS on Estuary (2026-09-22); second skin blocked by R-12** |
| 3 | Checksum every `SlideShow.xml` (`sha256sum`), answer **No**, checksum again | Identical; no `*.original` file; no leftover `.slideshow-bgm-write-probe`; the addon is still **enabled** in Add-ons | R-11, US2 sc. 1, SC-001, SC-002 — **PASS (2026-09-22)** |
| 4 | After No, start a slideshow | Runs normally, silently, no error | US2 sc. 4 |
| 5 | After No, restart Kodi | The dialog appears again | US2 sc. 3, SC-004 |
| 6 | Press **Back** or **Esc** on the dialog | Same outcome as No | US2 sc. 2, FR-005 |
| 7 | Answer **Yes** | Every resolution variant is hooked, each with a `.original` backup; log shows `consent granted` then `installed`; the next slideshow plays music | US1 sc. 3 |
| 8 | After Yes, restart Kodi | No dialog, and no wait either — an already-integrated skin skips `_wait_for_home` entirely | US3 sc. 1, SC-003 — **confirmed on Arctic Fuse 2/Horizon 2, 2026-09-22** |
| 9 | Disable the addon in Kodi, restart | No dialog. Re-enable it (hook still absent) | US2 sc. 5, Edge Case 5 — the dialog appears as soon as it is re-enabled |
| 10 | After Yes, switch to a skin that is not integrated, then restart or re-login | The dialog appears for that skin | US3 sc. 2 |
| 11 | Skin with several resolution variants, hook absent | Exactly **one** dialog | US3 sc. 4, SC-005 |
| 12 | Read-only skin, hook absent | **No** dialog; the failure toast appears; log shows the reason and remedy | Edge Case 2, FR-011 |
| 13 | Leave the dialog unanswered for a few minutes, start a slideshow | The dialog stays; nothing else breaks; the slideshow has no music | Edge Case 4, FR-009 |
| 14 | Switch Kodi's language to Korean, Spanish, French in turn and trigger the dialog | Localised heading and body; no raw `#32006` / `#32007` | SC-007, FR-012 — **PARTIAL FAIL on Korean/Spanish (2026-09-22): heading localized, body always showed English. Root-caused and fixed as D-019 — re-run to confirm** |

A failure of step 2 means shortening the wording further or reopening D-018 with the
evidence (R-9's note; the text viewer and a custom window were set aside on 2026-09-22);
a failure of step 1 triggers R-10's (now R-12's, since R-10 itself resolved); a
difference at step 3 triggers R-11's; a failure of step 14 triggers D-019's — re-check
every `msgid` is byte-identical across the four language files (guarded by
`tests/unit/test_strings.py`, but only for text that already shipped when the test was
added).
