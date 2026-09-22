# Phase 0 Research: Skin Integration Consent

**Branch**: `002-skin-hook-consent` | **Created**: 2026-09-21

Every decision below rests on one of three bases, labelled the same way as in
[001's research.md](../001-slideshow-bgm-playback/research.md):

- **API fact** — read directly from Kodi's own source (`Nexus` branch, the v20 floor).
- **Inference** — follows from API facts plus this codebase, but Kodi never states it.
- **Hypothesis** — unverified; must be checked against a running Kodi before merge.

Numbering **continues 001's sequence** (D-015, R-9, …) so a bare citation in a source
docstring is never ambiguous between the two specs.

---

## D-015: One blocking `yesno`, raised from the login service, for the consent question only

**Decision**: before any skin file is modified, `service.py` shows a single
`xbmcgui.Dialog().yesno(heading, message)` and acts on the answer. This deliberately
**supersedes**, for the consent question only, 001's 2026-09-11 clarification that "a
blocking dialog is too intrusive for something happening at profile login". Install
*failure* stays the non-blocking notification 001/FR-015 specifies.

**Rationale**: the two cases differ in kind, not just in degree. A failure notice reports
something that already happened, so a toast that can be missed is enough and a modal would
demand acknowledgement for nothing. Consent is a decision the addon **cannot proceed
without**: modifying a third-party file silently is precisely what this feature exists to
stop. `yesno` is the platform's own two-button primitive, and calling it synchronously
keeps constitution 2.2 intact — after `main()` returns nothing is left running.

**Alternatives considered**:

- A settings toggle ("allow skin modification"), default off, with a toast pointing to it
  — rejected: the addon would sit silently dormant until the user found the setting,
  which is the exact "no music and no visible cause" outcome FR-015 was written to avoid.
- A toast with an action — rejected: Kodi notifications carry no buttons.
- "Text viewer, then `yesno`" — rejected by the project owner on 2026-09-21 in favour of
  the single dialog the spec already promises (FR-008, SC-005), and on 2026-09-22
  withdrawn as a fallback too: the single dialog is final. A custom `WindowXMLDialog` was
  set aside the same day (D-018).

**Confidence**: **API fact** that `Dialog.yesno` is a blocking two-button call
(`xbmc/interfaces/legacy/Dialog.cpp`). The reversal itself is a project-owner decision,
not a technical one.

---

## D-016: "No" is a soft disable — never `Addons.SetAddonEnabled(false)`

**Decision**: answering No (or dismissing the dialog) writes nothing anywhere. The addon
stays enabled in Kodi; it is "inactive" only in that nothing was added to the skin, so no
slideshow ever launches it. The question returns at the next profile load because the
skin still lacks the hook.

**Rationale**: the requirement asks for two things that a Kodi-level disable makes
mutually exclusive — the addon "disabled", and the question "shown again the next time
Kodi starts". Kodi's service manager starts **only enabled** addons' services:

```cpp
// xbmc/addons/Service.cpp, CServiceAddonManager::Start()
VECADDONS addons;
if (m_addonMgr.GetAddons(addons, AddonType::SERVICE))
  for (const auto& addon : addons)
    Start(addon);
```

and `GetAddons(VECADDONS&, AddonType)` is documented in `AddonManager.h` as returning
"enabled add-ons with given type". A disabled addon's `service.py` therefore never runs at
the next launch, and the re-ask could not happen until the user re-enabled the addon by
hand — at which point `OnEvent(AddonEvents::Enabled)` calls `Start(addonId)` and the
dialog would appear. There is a second problem: `SetAddonEnabled(false)` from inside the
service emits `AddonEvents::Disabled`, whose handler calls `Stop(addonId)` on the very
script that issued the call.

**Consequence for the dialog text**: item (d) — "to stop being asked, disable or
uninstall the addon" — is exactly right under a soft disable. Under a hard disable it
would have been redundant, since the addon would already be disabled.

**Alternatives considered**: hard disable via JSON-RPC — rejected for the two reasons
above. A persisted "declined" flag that suppresses the question — rejected: the spec
requires the question to return (FR-005, FR-007).

**Confidence**: **API fact** for every claim about `Service.cpp` and `GetAddons`.
**Inference** that "no hook in the skin" is a sufficient inactive state, which holds
because 001/D-007 established the hook as the only thing that ever launches the addon.

---

## D-017: Assess before asking; nothing persisted; unmodifiable files excluded

**Decision**: split today's `install(path)` into two steps that share one inspection
routine.

1. `skinconnector.assess(path)` classifies a file, without modifying it, as
   `INTEGRATED`, `NEEDS_INTEGRATION`, or `NOT_MODIFIABLE`.
2. `service.py` asks only if at least one file is `NEEDS_INTEGRATION`, and on Yes calls the
   existing `install(path)` for exactly those files.

`install()` re-inspects each file itself, so a change that happens while the dialog is
open (the file was made read-only, or a skin update hooked it) is caught at write time
rather than trusted from the earlier assessment.

**Rationale**: the project owner settled on 2026-09-21 that a file the addon cannot
modify is not part of the question — a read-only skin would otherwise ask an unanswerable
question at every login. That requires the preconditions to run *before* the dialog. The
alternative, a second copy of the four checks in `assess()`, would let the question and
the install disagree about what "needs integration" means; one shared routine makes that
impossible. No consent record is stored (FR-007): whether the hook is present *is* the
record, and it is already reliable because 001 recognises the hook by its `RunAddon` text
alone.

**Observation, out of scope**: `install()` checks writability before checking whether the
hook is already present, so an already-hooked but read-only file is reported as a failure
on every login. Keeping that order preserves 001's behaviour exactly; reordering is a
separate decision.

**Confidence**: **Inference** — a design choice, not a Kodi behaviour. The one Kodi-side
assumption inside it is R-11.

---

## D-018: Single dialog; Estuary auto-scrolls the body; the injected line is not shown

**Decision**:

- ~~`skinconnector.hook_line()` returns the exact `<onload …>…</onload>` text, built from
  the same function `install()` uses, so the line in the dialog and the line in the file
  cannot differ (FR-003, SC-006).~~ **Withdrawn 2026-09-22**: the dialog no longer shows
  the line. It says in words that integration code is added and points to README.md's
  section "2. Skin integration" for the exact code. `hook_line()` and the helper that fed
  it were removed as dead code, and FR-003 and SC-006 with them.
- Dialog heading and body live in `strings.po` (#32006, #32007) in all four shipped
  languages. The body has **no placeholder** and is passed to the dialog unformatted.
- `messages.confirm(heading, message) -> bool` wraps `yesno` with **no** `autoclose`
  (FR-009) and returns `True` only for Yes.
- The dialog is a single `yesno`. "Text viewer, then `yesno`" and a custom
  `WindowXMLDialog` were both considered and set aside by the project owner on
  2026-09-22; the single dialog is final, not provisional.
- The body was condensed on 2026-09-22 into shorter full sentences and then, at the
  project owner's direction, stopped printing the injected line (English 542 → 364
  characters) to lessen the auto-scrolling. The "why it is harmless" reassurance went with
  the line, and FR-002(b) was rewritten to "where to read the details" (spec
  Clarifications 2026-09-22). The pointer is the README's section "2. Skin integration",
  not a URL: a Kodi dialog cannot follow a link, and a URL would cost about as much text
  as it saved. The trade-off: the user has to look outside Kodi to read the exact code.

**Rationale — what `yesno` returns**: the legacy binding is
`yesNoCustomInternal(...) == 1`, and `CGUIDialogYesNo` returns `-1` when the dialog was
cancelled. Back/Esc and "No" therefore both yield `False`, which is exactly the
equivalence FR-005 asks for — no `yesnocustom` is needed to tell them apart.

**Rationale — body length**: with the injected line the body came to about 11–15 lines
before the 2026-09-22 condensing and about 9–12 after. Without the line it is about 8–9
English lines (364 characters), 8–10 in Korean and 10–12 in Spanish and French — all
estimates at 50–60 characters per line (30–36 for Korean), not measured on a device. The
143-character line alone had been 3–4 of those lines, and contained an 84-character token
with no space to break at. Estuary's confirm dialog gives its text control a fixed height:

```xml
<!-- addons/skin.estuary/xml/DialogConfirm.xml -->
<control type="textbox" id="9">
  <height>165</height>
  <autoscroll time="3000" delay="4000" repeat="5000">true</autoscroll>
```

At 165 px only about five or six lines are visible at once; the rest is reached by
auto-scroll. The full text *is* reachable, and Yes/No stay focusable throughout, but it
cannot be read at a glance. Other skins may differ (R-9).

**Alternatives considered**:

- `Dialog.textviewer` for the explanation followed by a short `yesno` — better for
  reading, but two dialogs, so it would need FR-008/SC-005 reworded. Set aside.
- `Dialog.yesnocustom` with a third "details" button — no gain: FR-002 requires the four
  statements in the dialog itself, so they would still have to be in its body.
- A custom `xbmcgui.WindowXMLDialog` — the only way to get scrollable text and Yes/No in
  one window, but it means shipping skin XML, textures and fonts that must work across
  skins, and Tier 1 cannot verify how any of it renders. Set aside.
- A link to further reading — a Kodi dialog cannot follow one, so the required
  statements cannot move behind it.
- Shortening the body by dropping required items — rejected: FR-002 lists them as
  mandatory.

**Chosen (2026-09-22)**: keep the single `yesno` and condense the wording of the four
statements.

**Confidence**: **API fact** for `yesno`'s return semantics and for Estuary's text-control
geometry. **Hypothesis** that the resulting readability is acceptable — R-9.

---

## D-019: `msgid` must be byte-identical across every shipped language file

**Confirmed on real Kodi, 2026-09-22 (Tier 2 step 14)**: the consent dialog's heading
(#32006) localized correctly into Korean and Spanish; the body (#32007) always showed
English regardless of UI language.

**Root cause**, found in Kodi's own source after the fact: `#32007`'s `msgid` in
`resource.language.en_gb` had been hand-edited (dropping a `\n` before "However") without
the same edit landing in `ko_kr`/`es_es`/`fr_fr`'s copies of that `msgid`. Kodi's addon
string loader, `LoadWithFallback()` (`xbmc/guilib/LocalizeStrings.cpp`), always loads the
active UI language first and then **unconditionally** reloads `en_gb` afterward:

```cpp
static bool LoadWithFallback(const std::string& path, const std::string& language,
                              std::map<uint32_t, LocStr>& strings)
{
  std::string encoding;
  if (!LoadStr2Mem(path, language, strings, encoding))
    if (StringUtils::EqualsNoCase(language, LANGUAGE_DEFAULT))
      return false;
  if (!StringUtils::EqualsNoCase(language, LANGUAGE_DEFAULT))
    LoadStr2Mem(path, LANGUAGE_DEFAULT, strings, encoding);   // always re-read en_gb
  return true;
}
```

`LoadPO()` uses that second (English) pass as a staleness check, comparing the just-read
`en_gb` `msgid` against the `msgid` the translated file stored as its own reference copy
of the source text:

```cpp
if (bSourceLanguage && !PODoc.GetMsgid().empty())
{
  if (bStrInMem && (strings[id].strOriginal.empty() ||
                    PODoc.GetMsgid() == strings[id].strOriginal))
    continue;                                    // source unchanged -- keep the translation
  else if (bStrInMem)
    CLog::Log(LOGDEBUG, "POParser: id:{} was recently re-used in the English string "
              "file, which is not yet changed in the translated file. Using the "
              "English string instead", id);
  strings[id].strTranslated = PODoc.GetMsgid();   // mismatch -- overwrite with English
  ...
```

A `msgid` mismatch is silently read as "the English source changed since this string was
translated" and Kodi discards the translation — even though the `msgstr` translation
itself was completely correct. `POUtils.cpp`'s `GetString()` was checked and cleared as a
suspect: it bounds a quoted string by only the first and last character of its physical
line, so embedded escaped quotes (`\"2. Skin integration\"`) inside a single-line `msgid`
do not break parsing on their own — the earlier hypothesis that the escaped quotes
themselves were the cause was wrong.

**Fix**: `msgid` for every id is now required to be byte-identical across all four
language files (the four files' `msgid` differ from each other only in whether they hand
Kodi the reference copy of the English text — never in the text itself).
`tests/unit/test_strings.py::test_every_languages_msgid_matches_the_english_source_byte_for_byte`
guards this for every id, not just #32007, so any future hand-edit to one language file's
wording that misses the other three is caught before it reaches a device. `msgstr` (the
actual translation shown) is unaffected by this fix and keeps its own wording.

**Confidence**: **API fact**, confirmed against a real device and against
`LocalizeStrings.cpp`/`POUtils.cpp` source.

---

## D-020: Default focus is Yes, overriding Kodi's own default of No

**Decision** (2026-09-22, project-owner request): `messages.confirm()` passes
`defaultbutton=xbmcgui.DLG_YESNO_YES_BTN` to `yesno()`, so the dialog opens with **Yes**
focused.

**Rationale**: `xbmc/interfaces/legacy/Dialog.h` documents `yesno`'s `defaultbutton`
parameter, default `CONTROL_NO_BUTTON` — Kodi's own `CGUIDialogYesNo::Reset()`
(`xbmc/dialogs/GUIDialogYesNo.cpp`) confirms the same:
`m_defaultButtonId = CONTROL_NO_BUTTON`. Left at that default, a Select press the instant
the dialog opens — before the user has moved focus at all — declines. This addon asks the
question precisely because it needs Yes to do anything, so defaulting to Yes removes that
friction. The Python-exposed constant is `xbmcgui.DLG_YESNO_YES_BTN`, confirmed equal to
`CONTROL_YES_BUTTON` via a `SWIG_CONSTANT2` binding in `Dialog.h`; the underlying values
(`xbmc/dialogs/GUIDialogBoxBase.h`) are `CONTROL_CHOICES_START = 10`,
`CONTROL_NO_BUTTON = 10`, `CONTROL_YES_BUTTON = 11` — mirrored in the fake
(`tests/fakes/xbmcgui.py`) as `DLG_YESNO_NO_BTN`/`DLG_YESNO_YES_BTN`.

**Relationship to R-12's "no default focus" observation**: unrelated. That observation
was about a focus *indicator* apparently not rendering at all on Arctic Fuse 2 while its
own button textures were still being generated — a rendering question, not a question of
*which* button Kodi defaults to. This decision does not claim to explain or fix that; it
is an independent, deliberate UX choice.

**Confidence**: **API fact** — `defaultbutton`'s default and the constant values are
read directly from Kodi's own source, not inferred.

---

## Risks to retire in Tier 2

Each of these needs a running Kodi; green Tier 1 tests do not close them.

### R-9 — the consent text is readable enough

**Resolved on real Kodi, 2026-09-22: PASS on Estuary.** All four statements were legible,
by auto-scroll, before answering. Not yet checked on a second skin, since R-10's finding
below made that check moot for Arctic Horizon 2 / Arctic Fuse 2 (the dialog never reached
a readable, answerable state there at all).

### R-10 — a modal dialog raised from a service at startup behaves

**Resolved on real Kodi, 2026-09-22: PASS on Estuary, FAILED on Arctic Horizon 2 and
Arctic Fuse 2.** On the latter two: the skin's own initialization is completely blocked
while the dialog is showing; after an answer, the skin's initialization stays halted
rather than resuming; and neither button carries default focus (Estuary has none of these
problems). Tracked as **R-12** below rather than folded back into this entry, since it is
now a confirmed, skin-specific failure with its own remedy path, not an open hypothesis.
**Check**: quickstart.md Tier 2 steps 1 and 8 — **re-run 2026-09-22 after R-12's
`_wait_for_home` fix: PASS on Arctic Fuse 2 and Arctic Horizon 2**, both now behaving as
originally intended (no block, no halt after answering).

### R-12 — the consent dialog contends with a heavier skin's own boot sequence

**Confirmed on real Kodi, 2026-09-22 (Arctic Fuse 2, `kodi.log`)** — the exact collision,
not just a plausible mechanism:

```
12:07:08.628  load skin from: .../skin.arctic.fuse.2/
12:07:08.803  started alarm with name: splashtimeout
12:07:09.152  [slideshow-BGM] skin hook: consent requested for 1 file(s)
12:07:09.163  ------ Window Init (DialogConfirm.xml) ------      (opens window 10100)
   ...        (Arctic's own boot work: script.skinvariables, then script.texturemaker
               generating the skin's custom button/background textures)
12:07:09.763  Activating window ID: 10000
12:07:09.763  Activate of window '10000' refused because there are active modal dialogs
   ...        (nothing else happens; no retry)
12:08:55.748  (a mouse move is the first GUI activity in almost 3 minutes)
12:08:58.165  Stopping the application...                        (user gives up and quits)
```

Window ids confirmed against `xbmc/guilib/WindowIDs.h`: `10000` is `WINDOW_HOME`, `10100`
is `WINDOW_DIALOG_YES_NO` — our own consent dialog. The refusal is deliberate, documented
Kodi behavior, found in `xbmc/guilib/GUIWindowManager.cpp`:

```cpp
// don't activate a window if there are active modal dialogs of type MODAL
if (!force && HasModalDialog(true))
{
  CLog::Log(LOGINFO, "Activate of window '{}' refused because there are active modal
            dialogs", ...);
  return;   // dropped -- not queued, never retried by the window manager itself
}
```

**Mechanism**: Arctic Fuse 2 runs its own splash/startup window
(`Custom_1198_Window_Startup.xml`) with a timed alarm (`splashtimeout`, via Kodi's
`AlarmClock`) that, on expiry, activates Home (window `10000`) to leave the splash screen.
That alarm expired while our consent dialog (window `10100`) was still open, and Kodi's
window manager dropped the activation outright rather than queuing or retrying it —
`ActivateWindow` has no such fallback. Nothing in the skin retries afterward, so once
refused, the skin is stuck on its splash screen with no further attempt to reach Home;
in this run the user waited almost three minutes with no GUI activity before quitting
Kodi. This is not Arctic-specific in mechanism — any skin that schedules its own
splash-to-Home (or similar) transition on a timer is exposed to the same race, since our
dialog's open duration is however long the user takes to answer, unbounded (FR-009).

The originally reported "no button focus" is not fully explained by this log: the Enter
key **was** routed to window `10100` and handled as `action is Select`, so a control did
have focus and accept input. `script.texturemaker` was still generating Arctic's own
button textures (`circlebuttondialog=...`) concurrently while the dialog was open; a focus
*indicator* failing to render because its texture did not exist yet is a plausible
explanation for what looked like "no focus", but this is inference, not confirmed by the
log the way the window-activation refusal is.

**Fix implemented 2026-09-22** (`service.py` `_wait_for_home`): before assessing or asking
— and only when at least one file is actually pending, so an already-integrated skin never
waits — wait (abort-aware, `xbmc.Monitor().waitForAbort(0.5)`, matching D-002's existing
pattern) for `xbmc.getCondVisibility('Window.IsActive(home)')`, capped at 10 s (20
iterations) so a skin with no "Home" concept, or one that never settles, still gets asked
rather than blocked forever (fail open); a `LOGWARNING` is logged if the cap is hit. This
targets the confirmed mechanism directly (no modal exists yet when the skin attempts its
own transition) rather than guessing at a fixed delay.

**Constitution scrutiny**: 1.2 (longest workable wait interval) — 0.5 s reuses D-002's
own interval rather than inventing a shorter one. 2.2 (service holds nothing after
`main()` returns) — the wait is a loop entirely inside `main()`'s call stack; it is
`service.py`'s first wait of any kind, but nothing persists past it, so no new violation.

**TDD**: `tests/integration/test_consent_flow.py` — a `home_already_active` autouse
fixture defaults every other test to the fast path; five tests pin the new behaviour
(skip entirely with nothing pending; skip when Home is already active; give up and log
after exactly 20 calls when Home never activates; stop after exactly 1 call when Kodi's
own abort fires; the dialog still appears in the give-up case). Five deliberate mutations
(no wait at all; a shrunk cap; ignoring abort; waiting with nothing pending; dropping the
log line) were each caught by this set and reverted. 472 passed; gates clean.

**Check**: quickstart.md Tier 2 steps 1 and 8 — **confirmed on real Kodi, 2026-09-22: PASS
on both Arctic Fuse 2 and Arctic Horizon 2.** Tier 1 had only proven the wait behaves as
designed; this is the real-device evidence that waiting for Home actually prevents the
collision in practice. R-12 is closed.

### R-11 — the pre-consent probes leave the skin file's content untouched

**Hypothesis**: `assess()`'s write probe — an empty append to the skin file and a
transient probe file in its directory, the same probes 001 already runs on every login —
leaves the skin file **byte-identical**. SC-001 asserts byte-identity, not an unchanged
modification time, which the empty append may or may not disturb. The probe file is not a
skin file and is deleted immediately, but it does briefly exist in the skin's directory
before the user has answered; the project owner accepted this by choosing to exclude
unmodifiable files from the question (spec Clarifications), which is what makes the probe
necessary before asking. **Check**: quickstart.md Tier 2 step 3 — compare a checksum of
each `SlideShow.xml` before and after a declined run.

---

## Status of each basis

| Question | Answer | Basis |
|---|---|---|
| Does Kodi start a disabled addon's service at launch? | No — `GetAddons(…, SERVICE)` is enabled-only | API fact (`Service.cpp`, `AddonManager.h`) |
| Does enabling an addon start its service immediately? | Yes — `OnEvent(Enabled)` → `Start(addonId)` | API fact (`Service.cpp`) |
| What does `Dialog.yesno` return for No vs Back/Esc? | `False` for both | API fact (`Dialog.cpp`, `GUIDialogYesNo.cpp`) |
| Does the dialog time out by default? | No — `autoclose` defaults to 0 | API fact (`Dialog.cpp`) |
| Does Estuary show the whole body at once? | No — fixed 165 px text control with auto-scroll | API fact (`DialogConfirm.xml`) |
| Is the auto-scrolled body readable enough? | Yes on Estuary | **API fact (real device) — R-9** |
| Does a startup service dialog behave? | Yes on Estuary; on Arctic Fuse 2/Horizon 2, a skin-side timed transition was refused while the dialog was open and never retried — fixed by waiting for Home first, confirmed on both skins | **API fact (real device + `GUIWindowManager.cpp`) — R-10, R-12 (closed)** |
| Do the pre-consent probes leave content byte-identical? | Expected, unverified | **Hypothesis — R-11** |
| Is "hook absent" a sufficient inactive state? | Yes | Inference (001/D-007) |
| Must every language file's `msgid` for one id be identical? | Yes — a mismatch makes Kodi discard the translation | **API fact (real device + `LocalizeStrings.cpp`) — D-019** |
