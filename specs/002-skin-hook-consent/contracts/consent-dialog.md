# Contract: Skin Integration Consent Dialog

**Consumers**: the user at profile login, `service.py`, `resources/lib/skinconnector.py`,
`resources/lib/messages.py`

**Source decisions**: [research.md D-015..D-018, R-12](../research.md). **Requirements**:
[spec.md](../spec.md) FR-001..FR-012.

**Extends** [001's skin-integration contract](../../001-slideshow-bgm-playback/contracts/skin-integration.md):
everything there about *how* the hook is installed — backup, every resolution variant, no
duplicates, failure reporting — is unchanged. This contract adds only *whether* and *when*
the install is allowed to run.

## When the dialog appears

At profile login, from `service.py`, **only** when at least one of the active skin's
`SlideShow.xml` files is `NEEDS_INTEGRATION` — present, readable, writable, parseable, and
lacking the hook ([data-model.md](../data-model.md)). It appears **once** per run however
many files are pending.

Before it appears, the run waits (abort-aware, capped at 10 s) for
`xbmc.getCondVisibility('Window.IsActive(home)')` — but only when something is actually
pending; a skin that needs no consent never waits at all. This closes R-12, confirmed on
real Kodi: a skin that schedules its own splash-to-Home transition on a timer can have
that transition dropped by Kodi's window manager if it lands while our dialog is already
open, and the drop is never retried, stranding the skin on its splash screen. Waiting for
Home first removes the race. If Home never becomes active within the cap, the run logs a
warning and asks anyway (fail open) — see [research.md R-12](../research.md).

It does **not** appear when:

- every file already carries the hook, including hooks installed by earlier versions;
- no file could be found;
- every file that lacks the hook is unmodifiable (the failure toast covers those).

## The dialog

A single `xbmcgui.Dialog().yesno(heading, message, defaultbutton=xbmcgui.DLG_YESNO_YES_BTN)`
— Kodi's default **Yes** / **No** buttons, no custom labels, **no `autoclose`**: it waits
for an answer. Focus opens on **Yes**, not Kodi's own default of No (D-020) — this asks
the question precisely because Yes is what the addon needs to do anything.

Text comes from `strings.po` by id and is passed to the dialog as it is — nothing formats
it; no literal appears in code. English source (`resource.language.en_gb`):

| Id | Role | English text |
|---|---|---|
| `#32006` | Heading | `Slideshow-BGM needs your permission` |
| `#32007` | Body — plain text, **no placeholder** | `Slideshow-BGM must add integration code to the current skin's SlideShow.xml so that it can run automatically when a slideshow starts. For details, see "2. Skin integration" in README.md.\nIf you choose No, nothing changes and the addon stays inactive.\nHowever, you will be asked again at the next start or login. To stop being asked, disable or uninstall the addon.` |

The body was condensed on 2026-09-22 from a longer five-paragraph wording (542 → 364
English characters) to lessen Estuary's auto-scrolling; the dialog stays a single `yesno`
(research.md D-018, spec Clarifications 2026-09-22). The last step removed the injected
line from the dialog and pointed to the README instead, so the "why it is harmless"
reassurance and the shown-equals-written guarantee (FR-003, SC-006) went with it.

**What every translation MUST convey** (FR-002), with no `{` or `}` anywhere in the text —
nothing formats the body, so a leftover placeholder would be shown literally:

1. The addon must add integration code to the current skin's `SlideShow.xml` so that it can
   run automatically when a slideshow starts. The file name stays `SlideShow.xml`.
2. Where to read the details: `README.md`, section `2. Skin integration` — the file name and
   the section title kept exactly as written, untranslated, because the README is English.
3. Answering **No** cancels the change and leaves the addon inactive, and the question
   returns at the next Kodi start or login.
4. To stop being asked, disable or uninstall the addon.

Spanish and French are drafted alongside the English and marked for native-speaker review
in the commit that adds them; a review may improve wording but must not drop a statement.

## Answers

| Answer | Effect |
|---|---|
| **Yes** | Log `consent granted`; call `install(path)` for **every** pending path, attempting all even if one fails (001/FR-015) |
| **No** | Log `consent declined`; modify nothing, back up nothing |
| **Back / Esc** | Identical to **No** — `yesno` returns `False` for both, and no attempt is made to tell them apart |
| *(no answer)* | The run waits. Nothing else in Kodi is affected; slideshows play without background music (Edge Case 4) |

After **No** the addon remains **enabled** in Kodi. It is inactive only because nothing was
added to the skin. It MUST NOT call `Addons.SetAddonEnabled` (D-016).

## Nothing is remembered

No setting, file or flag records an answer (FR-007). Each login re-derives the question
from the skin files, so a changed skin or a skin update that dropped the hook re-asks, and
an already-integrated skin never does.

## Log events

Header and levels per [001's logging contract](../../001-slideshow-bgm-playback/contracts/logging.md).
Each occurs exactly once per run at `LOGINFO` (FR-010):

| Event | Message shape |
|---|---|
| Consent requested | `skin hook: consent requested for <n> file(s)` |
| Consent granted | `skin hook: consent granted` |
| Consent declined or dismissed | `skin hook: consent declined or dismissed — skin left untouched; will ask again at next profile load` |

`installed (<path>)`, `already present (<path>)` and `install failed at <path> — …` are
unchanged. The generic failure toast is unchanged and stays non-blocking (FR-011).

## Module interfaces

```python
# resources/lib/skinconnector.py
class SlideshowFileState(enum.Enum):
    INTEGRATED = "integrated"
    NEEDS_INTEGRATION = "needs_integration"
    NOT_MODIFIABLE = "not_modifiable"

def assess(path: str) -> SlideshowFileState:
    """Classify one file without modifying it. Logs exactly what install() would."""

# resources/lib/messages.py
def confirm(heading: str, message: str) -> bool:
    """Blocking Yes/No, focused on Yes (D-020). True only for Yes; No, Back and
    Esc are False. No autoclose."""
```

**Contracts**:

- `assess()` and `install()` share one inspection routine, so they cannot disagree about
  what a file is (D-017). `install()` keeps its public behaviour and its return value.
- `install()` re-inspects when called, so a file that changed while the dialog was open is
  caught at write time.
- There is no `hook_line()`: it existed only to keep the line shown in the dialog equal to
  the line written (FR-003, SC-006), and was removed on 2026-09-22 with the requirement.
- `messages.confirm` is the **first blocking-dialog wrapper since 2026-09-15**, when
  `ok`/`yesno` were removed with their only caller. It exists for this one question; every
  other surface stays non-blocking (D-015). `messages` remains the only module that
  constructs an `xbmcgui.Dialog`.
- `service.main()` holds no thread, timer or listener after it returns (constitution 2.2);
  the dialog is a synchronous call.

## Dependency direction

Unchanged from 001, and still acyclic:

```text
service.py ──> skinconnector ──> messages
service.py ──> messages   (the consent dialog and the FR-015 failure notification)
```

## Documents this contract obliges the implementation to update

They describe code that does not exist until the feature does, so they change with it:

- 001 `contracts/skin-integration.md` — the Lifecycle table's login row, and the paragraph
  saying neither failure surface is a blocking dialog (still true for *failures*; it now
  needs to say the consent question is the exception).
- 001 `contracts/modules.md` — the `skinconnector` and `messages` signatures, the entry
  point docstring for `service.py`, and the "deliberately no blocking-dialog wrapper"
  paragraph.
- 001 `contracts/logging.md` — the three consent events.
- `resources/lib/messages.py` module docstring — same "deliberately no blocking-dialog
  wrapper" claim.
- `CLAUDE.md` symptom map — a row for consent behaviour → D-015..D-018, R-9..R-11.
- `README.md` — wherever it describes the skin integration.
