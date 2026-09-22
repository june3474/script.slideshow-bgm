# Contract: Skin Integration (`SlideShow.xml` onload hook)

**Consumers**: the active Kodi skin, `service.py`, `resources/lib/skinconnector.py`

**Source decision**: [research.md D-007](../research.md); justified against constitution
principle 2.2 in [plan.md](../plan.md) Complexity Tracking.

A Script Mode addon cannot launch itself. This hook is what makes FR-001 ("begin playing
background music automatically when a slideshow starts") possible at all: it is the sole
mechanism by which Kodi is told to run the addon when the slideshow window opens.

## The element

Injected as the last child of the root `<window>` element of the active skin's
`SlideShow.xml`:

```xml
<onload condition="System.HasAddon(script.slideshow-bgm) + System.AddonIsEnabled(script.slideshow-bgm)">RunAddon(script.slideshow-bgm)</onload>
```

The `condition` guard is load-bearing, not decorative: it makes the injected line inert
if the addon is later uninstalled or disabled, so a stale hook can never break the user's
slideshow window.

**Identification**: the hook is recognized by its `RunAddon(script.slideshow-bgm)` text
content, not by position or by the exact condition string. A hook whose text matches but
whose condition differs is treated as present and left untouched — the user may have
edited it deliberately.

## File location

`SlideShow.xml` is found by resolving `special://skin` and searching its resolution
subdirectories (e.g. `1080i/`, `16x9/`) for a file named `SlideShow.xml`,
case-insensitively. If more than one is found, every one of them is hooked — Kodi picks
the resolution directory at runtime.

All filesystem access uses `xbmcvfs` (`exists`, `File`, `copy`, `listdir`), never `os.*`,
for the non-ASCII path reason in [research.md D-009](../research.md).

## Operations

| Operation | Contract |
|---|---|
| `is_hooked(path) -> bool` | True iff an `<onload>` whose text is `RunAddon(script.slideshow-bgm)` exists under the root `<window>` |
| `install(path) -> bool` | Back up, then insert the element. No-op returning `True` if already hooked |
| `uninstall(path) -> bool` | Remove only the addon's own `<onload>`; leave every other element untouched |
| `assess(path) -> SlideshowFileState` | *(added 2026-09-21, [specs/002](../../002-skin-hook-consent/contracts/consent-dialog.md))* Run the same preconditions as `install` and classify the file `INTEGRATED` / `NEEDS_INTEGRATION` / `NOT_MODIFIABLE` without modifying it; logs exactly what `install` would |

### Preconditions for `install`

Checked in this order; the first failure aborts with no write to that file:

1. A `SlideShow.xml` was found under `special://skin` for the active skin.
2. It is readable.
3. Both the file and its containing directory are writable.
4. It parses as XML with a root `<window>` element.

A failure is never fatal to Kodi or to the slideshow — the addon simply stays dormant.
It is also never silent (added 2026-09-11, FR-015): each failure is logged with the
specific reason and a suggested remedy, and `service.py` shows one non-blocking
notification for the run, naming the failure generically and pointing at the log for
detail. Neither is a blocking dialog — profile login is not a moment to demand
acknowledgement, but a failure that leaves the user without background music and no
visible cause is worse than a brief toast. **[AMENDED 2026-09-21]** This holds for
*failures*. The one blocking dialog is the consent question asked **before** an install
— see "Consent before install" below.

### Consent before install (added 2026-09-21, specs/002)

`service.py` no longer installs blind. It first `assess()`es every file — the same
preconditions, and no write to the skin file — and only if at least one is
`NEEDS_INTEGRATION` asks the user, once, through a blocking Yes/No dialog whose text says
what will be added and points to README.md's section "2. Skin integration" for the exact
code. **Yes** → `install()` for those files, exactly as specified here.
**No** or Back/Esc → nothing is modified or backed up, the addon stays enabled but inactive
(nothing launches it), and the question returns at the next profile load. Nothing is
persisted: the hook's presence is the record. A file that fails a precondition is not part
of the question and follows the failure path above. Full contract:
[specs/002 consent-dialog.md](../../002-skin-hook-consent/contracts/consent-dialog.md).

| Failure | Logged reason (example) | Logged remedy |
|---|---|---|
| Not found | `no SlideShow.xml found under special://skin for skin <skin_id>` | "this skin may not support slideshow integration; try a different skin" |
| Not readable | `SlideShow.xml exists but is not readable: <path>` | "check file permissions for the user running Kodi" |
| Not writable | `SlideShow.xml or its directory is not writable: <path>` | "grant write permission, e.g. chmod u+w <path> or edit <path> using sudo, then restart Kodi" |
| Parse failure | `SlideShow.xml is not valid XML or has no root <window>: <path>` | "the skin file may be corrupted; try reinstalling the skin" |

The "not writable" row is the one most users hit in practice — Linux and macOS installs
where Kodi's addon and skin directories are owned by another user are the common case.
The notification text itself stays generic ("Slideshow-BGM integration failed — see
kodi.log") on purpose: reason and remedy are detailed enough to need the log's room, and
a toast that tried to carry them would either truncate or overstay its welcome. Exact
message shapes are fixed in [logging.md](./logging.md).

### Backup

Before the **first** edit of a given file, copy it to `<slideshow_xml_path>.original`. If
that file already exists it is **not** overwritten — it must remain a copy of the skin's
pristine original, not of a previously hooked version.

### Idempotency

`install` is safe to call on every profile login and MUST NOT accumulate duplicate
`<onload>` elements. This is what makes the run-once service safe to re-run and what
re-hooks the addon after the user changes skins (risk R-3).

## Lifecycle

| Moment | Actor | Action |
|---|---|---|
| Profile login / Kodi start | `service.py` (`xbmc.service` extension point) | Resolve active skin, `assess()` each file, ask the user once if any needs the hook *(specs/002)*, `install()` the ones that do on Yes, **exit immediately** |
| Skin change by the user | next profile login | Re-`assess()`; the new skin's files are asked about if they lack the hook |
| Slideshow window opens | Kodi | Evaluates the condition, runs `RunAddon(script.slideshow-bgm)` |
| Addon uninstall | Kodi | Hook remains but its condition evaluates false — inert |

**Constitution constraint (2.2)**: `service.py` MUST hold no threads, timers, listeners,
or `Monitor` instances after `install()` returns. It runs, hooks, and exits — any code
that makes it outlive its hookup work breaks the deviation justified in
[plan.md](../plan.md) Complexity Tracking.

## Known limitation

A skin update can overwrite `SlideShow.xml` and silently drop the hook (risk R-3),
repaired only at the next profile login — and, since 2026-09-21, only if the user agrees
again, because no answer is remembered (specs/002 FR-007). Why this is preferred over watching the file is
argued in [research.md](../research.md) D-007. If that repair attempt also fails, the same
notify-and-log behavior above applies — there is only one failure path, not a separate one
for first install versus re-install.
