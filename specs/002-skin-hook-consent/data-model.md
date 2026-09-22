# Phase 1 Data Model: Skin Integration Consent

**Branch**: `002-skin-hook-consent` | **Created**: 2026-09-21

Everything here is in-memory and lives for the duration of one `service.main()` run.
**Nothing is persisted** (FR-007): no setting, no file, no flag. The one durable fact —
whether a skin file carries the hook — already lives in the skin file itself, and it is
what makes "asked again next login" work without a store.

## `SlideshowFileState` — per-file classification (Key Entity: Slideshow File)

Produced by `skinconnector.assess(path)`. Exactly one value per file.

| Value | Meaning | Asked about? | Touched on Yes? |
|---|---|---|---|
| `INTEGRATED` | Carries the addon's `RunAddon(script.slideshow-bgm)` `<onload>` — whatever its condition says (001/D-007) | No | No |
| `NEEDS_INTEGRATION` | Passed every precondition and lacks the hook | **Yes** — the only state that triggers the dialog | Yes |
| `NOT_MODIFIABLE` | Missing, unreadable, not writable, or not a parseable `<window>` (Edge Case 2) | No | No |

**Assessment order** — identical to 001's `install()` preconditions, then the hook check,
because both are the same routine (D-017). The first hit decides and stops:

| Step | Check | Outcome when it hits | Logged (unchanged from 001) |
|---|---|---|---|
| 1 | File exists | `NOT_MODIFIABLE` | `LOGERROR` skin hook: install failed at … — no SlideShow.xml found… |
| 2 | Readable | `NOT_MODIFIABLE` | `LOGERROR` … not readable … |
| 3 | File **and** its directory writable | `NOT_MODIFIABLE` | `LOGERROR` … not writable … |
| 4 | Parses with a root `<window>` | `NOT_MODIFIABLE` | `LOGERROR` … not valid XML … |
| 5 | Hook present | `INTEGRATED` | `LOGDEBUG` skin hook: already present (`<path>`) |
| 6 | (none of the above) | `NEEDS_INTEGRATION` | — |

`assess()` never writes to the skin file. Its writability probe is the same empty append
plus transient probe file 001 already performs at every login (R-11).

## `ConsentRequest` — the question (Key Entity: Consent Request)

Transient value built once per run.

| Field | Type | Notes |
|---|---|---|
| `pending` | `List[str]` | Paths in `NEEDS_INTEGRATION`, in the order `find_slideshow_xml()` returned them |
| `outcome` | `GRANTED` \| `DECLINED` | `DECLINED` covers No **and** Back/Esc — `yesno` returns `False` for both (D-018) |

**Rules**:

- Exists **iff** `pending` is non-empty (FR-006). A run with nothing pending never builds
  one, so an integrated skin can never produce a dialog.
- At most one per run, however many files are pending (FR-008, SC-005).
- Never stored; the next run rebuilds it from the skin files alone (FR-007).
- No timeout: the run blocks in the dialog until the user answers (FR-009).

## `IntegrationLine` — what gets written (Key Entity)

The one element `install()` appends to a slideshow file:

```xml
<onload condition="System.HasAddon(script.slideshow-bgm) + System.AddonIsEnabled(script.slideshow-bgm)">RunAddon(script.slideshow-bgm)</onload>
```

Built from `HOOK_CONDITION` and `HOOK_TEXT`. It is documented for users in README.md's
section "2. Skin integration", which the consent dialog points to. Until 2026-09-22 the
dialog showed it verbatim, and a `hook_line()` function kept the shown and written text in
step (FR-003, SC-006); the dialog no longer shows it, so that function and both
requirements were removed.

## Run flow

```text
find_slideshow_xml()
   │  no files ───────────────────────────────► log + failure toast   (001, unchanged)
   ▼
assess(path) for every path                 ← one pass; failures logged here
   │
   ├─ no NEEDS_INTEGRATION ─────────────────► done
   │
   └─ ≥1 NEEDS_INTEGRATION
         │  log "consent requested"
         ▼
      confirm(heading, body)                ← the ONLY blocking call, once per run
         │
         ├─ False (No / Back / Esc) ────────► log "consent declined"; touch nothing
         │
         └─ True ─► log "consent granted"
                    install(path) for every pending path   ← attempts all, none skipped
   ▼
any NOT_MODIFIABLE, or any install() returned False?
   ├─ yes ──► exactly one non-blocking failure toast for the run   (001, unchanged)
   └─ no ───► silent
```

## Outcomes by scenario

| Files found | Answer | Dialog | `install()` calls | Failure toast |
|---|---|---|---|---|
| None | — | No | 0 | Yes (001's not-found path) |
| All `INTEGRATED` | — | No | 0 | No |
| All `NEEDS_INTEGRATION` | Yes | Once | every file | Only if one fails |
| All `NEEDS_INTEGRATION` | No / Back | Once | 0 | No |
| Some `INTEGRATED`, some `NEEDS_INTEGRATION` | Yes | Once | the needy ones only | Only if one fails |
| Some `INTEGRATED`, some `NEEDS_INTEGRATION` | No / Back | Once | 0 — integrated ones are never removed | No |
| Some `NEEDS_INTEGRATION`, some `NOT_MODIFIABLE` | Yes | Once | the needy ones only | **Yes** (for the unmodifiable ones) |
| Some `NEEDS_INTEGRATION`, some `NOT_MODIFIABLE` | No / Back | Once | 0 | **Yes** |
| Only `NOT_MODIFIABLE` | — | No | 0 | Yes |

## Persistent state

None. Contrast 001, whose `BgmSource` and `BgmPosition` live in settings and memory; this
feature adds no setting and no store, and 3.1's "all configuration through
`settings.xml`" is trivially satisfied because there is no configuration.
