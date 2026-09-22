# Feature Specification: Skin Integration Consent

**Feature Branch**: `002-skin-hook-consent` (spec directory name only — work proceeds
directly on `main`, decided 2026-09-21)

**Created**: 2026-09-21

**Status**: Draft

**Input**: User description: Before the addon modifies the active skin's slideshow
file (the integration installed at profile login — 001's FR-015), ask the user for
consent through a Yes/No dialog that explains what will be changed, and act on the
answer: Yes proceeds with the existing integration, No leaves the skin untouched and
the addon inactive.

## Clarifications

### Session 2026-09-21

- Q: When the user answers No, the addon is to be "disabled" and the question is to
  return at the next Kodi start or profile load. Kodi does not start a disabled addon's
  login-time service (source-confirmed: only enabled addons' services are started at
  launch, and re-started only when the user re-enables the addon), so a Kodi-level
  disable would make the question impossible to ask again. Which "disabled" is meant? →
  A: Soft disable. The addon stays enabled in Kodi, nothing is added to the skin (so no
  slideshow ever launches the addon), and the question is asked again at every profile
  load while the integration is missing. To stop being asked, the user disables or
  uninstalls the addon — which is exactly the remedy the dialog itself names.
- Q: Should a Yes be remembered, so that a skin change or a skin update that drops the
  integration is re-installed without asking again? → A: No. Nothing is persisted. The
  question is asked whenever a slideshow file actually needs modification, and only
  then.
- Q: What about users whose skin was already integrated by an earlier version (1.0.1 and
  before)? → A: They see no dialog and nothing changes for them. This consent covers
  future modifications, not retroactive approval of earlier ones.
- Q: Should a slideshow file the addon cannot modify (missing, unreadable, not writable,
  malformed) be part of the consent question? → A: No. Only files that passed every
  precondition are asked about; the rest keep 001/FR-015's non-blocking notification
  and log. If none passed, no dialog appears. Otherwise a read-only skin would ask a
  question that cannot succeed at every login.
- Q: Which branch carries this work? → A: `main` directly, no feature branch.
- Defaults stated to the user and not objected to: Back/Esc counts as No; the dialog has
  no timeout.

### Session 2026-09-22

- Q: Estuary's Yes/No dialog shows only about five lines of its body at once and scrolls
  the rest, so the four required statements plus the injected line are slow to read.
  Should the explanation move to a text viewer shown before a short Yes/No question, or
  to a dialog layout of the addon's own? → A: No. The consent stays a **single Yes/No
  dialog**, and that is final rather than provisional. The wording of the four
  statements is condensed into shorter full sentences instead (English 542 → 427
  characters after the project owner's own edit; the other languages by a similar
  amount). No "more information" link is added: a Kodi dialog cannot follow one, so
  nothing required may sit behind it. All four statements and the exact line remain in
  the dialog itself.
- Q: The project owner's edit of the English wording drops the explanation *why* the line
  is harmless (that it only takes effect while the addon is installed and enabled).
  Restore it, or relax FR-002(b)? → A: Relax FR-002(b) (and User Story 1's scenario 2
  with it). The dialog still tells the user the line is harmless in nearly all cases; it
  no longer has to say why. The guard condition is still explained in the README and in
  the line the dialog shows, whose `condition` names both checks. This is a deliberate
  trade of some reassurance for shorter text.
- Q: (supersedes the two answers above on the shown line and on reassurance) The injected
  line is the longest single item in the dialog, and showing it is most of what makes the
  dialog slow to read. Should the dialog still show it? → A: No. The dialog says in
  words that integration code is added to the current skin's SlideShow.xml so that the
  addon runs automatically when a slideshow starts, and sends the user to README.md's
  section "2. Skin integration" for the exact code and what it does. **FR-003 and SC-006**
  (the shown line equals the written line) are withdrawn, and so is the "harmless in
  nearly all cases" reassurance the dialog carried; the README now carries both. The
  trade-off is that the user has to look outside Kodi for the exact code, because a Kodi
  dialog cannot open a README. English is now 364 characters (from 542); the longer
  Spanish and French run to about 10–12 estimated lines.

**Relationship to 001**: this feature deliberately **supersedes**, for the consent
question only, 001's 2026-09-11 clarification that "a blocking dialog is too intrusive
for something happening at profile login". Reporting of an install *failure* stays a
non-blocking notification exactly as 001/FR-015 specifies — only the consent question
is a blocking dialog, because unlike a failure notice it is a decision the addon cannot
proceed without.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Understand and Approve the Skin Change (Priority: P1)

A user installs the addon and their profile loads with a skin whose slideshow file does
not yet carry the addon's integration. Before anything is changed, a dialog explains that
the addon needs to modify that file, says what it will add and where to read the details,
and asks Yes or No. The user chooses Yes and the integration is installed exactly as it always was, so
background music plays in the next slideshow.

**Why this priority**: Consent to modify a third-party file is the point of the feature,
and Yes is the path that keeps the addon working at all.

**Independent Test**: With a skin whose slideshow file is not integrated, load the
profile, confirm the dialog appears and that the file is byte-identical while it is open,
answer Yes, and confirm the integration is present afterwards and a slideshow plays
background music.

**Acceptance Scenarios**:

1. **Given** the active skin has a slideshow file that lacks the integration, **When**
   the profile loads, **Then** a Yes/No dialog appears before any skin file is modified,
   and no skin file is modified — nor any backup created — while it is open.
2. **Given** the dialog is showing, **When** the user reads it, **Then** it states that
   (a) using the addon requires adding integration code to the current skin's
   SlideShow.xml so that it runs automatically when a slideshow starts, (b) where to
   read exactly what is added and what it does — README.md, section "2. Skin
   integration", (c) choosing No cancels the
   change and leaves the addon inactive, and the same question returns the next time Kodi
   starts or the profile loads, and (d) to stop being asked, the user should disable or
   uninstall the addon.
3. **Given** the dialog is showing, **When** the user answers Yes, **Then** the
   integration is installed as 001/FR-015 specifies — a backup of each modified file
   first, every resolution variant covered, no duplicate added — and the next slideshow
   plays background music.

---

### User Story 2 - Decline Without Side Effects (Priority: P1)

A user does not want their skin modified. They answer No (or press Back/Esc). Nothing is
changed, the addon does nothing, and the user is told up front how to stop being asked.

**Why this priority**: A consent prompt that cannot be safely declined is not consent;
this is the other half of the same decision and equally load-bearing.

**Independent Test**: With a skin whose slideshow file is not integrated, answer No and
confirm the file and its directory are unchanged, the addon is still enabled in Kodi, and
a slideshow plays without background music; then restart Kodi and confirm the dialog
returns.

**Acceptance Scenarios**:

1. **Given** the dialog is showing, **When** the user answers No, **Then** no skin file
   is modified, no backup is created, and the addon remains enabled in Kodi.
2. **Given** the dialog is showing, **When** the user dismisses it with Back/Esc,
   **Then** the outcome is identical to answering No.
3. **Given** the user declined and the skin still lacks the integration, **When** Kodi is
   restarted or the profile loads again, **Then** the same dialog appears again.
4. **Given** the user declined, **When** they start a slideshow, **Then** the slideshow
   runs normally with no background music and nothing else is affected.
5. **Given** the user disables or uninstalls the addon, **When** Kodi next starts,
   **Then** the dialog does not appear.

---

### User Story 3 - No Interruption Where No Consent Is Needed (Priority: P2)

A user whose skin is already integrated — including everyone who installed an earlier
version — is never asked anything. A user whose integration later disappears (they change
skin, or a skin update overwrites the file) is asked again, once.

**Why this priority**: Correctness of *when* to ask matters for trust, but the feature
already delivers its value without it, so it ranks below the two decision paths.

**Independent Test**: Load the profile with an integrated skin and confirm no dialog and
no file change; then remove the integration (or switch to another skin) and confirm the
dialog appears exactly once for the whole set of that skin's slideshow files.

**Acceptance Scenarios**:

1. **Given** every slideshow file of the active skin already carries the integration,
   **When** the profile loads, **Then** no dialog appears and no file is touched.
2. **Given** the user answered Yes earlier, **When** they switch to a skin that is not
   integrated, **Then** the dialog appears again for that skin.
3. **Given** the user answered Yes earlier, **When** a skin update removes the
   integration, **Then** the dialog appears again at the next profile load.
4. **Given** the active skin has several slideshow files (resolution variants) that need
   the integration, **When** the profile loads, **Then** exactly one dialog appears and
   its answer applies to all of them.

---

### Edge Cases

1. What happens when only some of the skin's slideshow files carry the integration? The
   dialog appears because at least one file lacks it. Yes integrates the missing ones;
   No changes nothing — files that already carry it are never removed.
2. What happens when a slideshow file cannot be modified at all — missing, unreadable,
   not writable, or malformed? It is not part of the question, since the user cannot act
   on it. It is reported through 001/FR-015's existing non-blocking notification and log.
   If no file can be modified, no dialog appears.
3. What happens when a user has hand-edited the injected line's condition? The line is
   still recognized as present (001's contract identifies it by its launch text alone), so
   no dialog appears and the file is left as it is.
4. What happens when nobody answers — for example an unattended media box at boot? The
   dialog stays until someone does. Nothing else is affected: the addon is simply dormant
   until the question is answered, and slideshows play without background music.
5. What happens when the user disables the addon and later re-enables it while the
   integration is still missing? Kodi starts the addon's service on re-enable, so the
   dialog appears again.
6. What happens when the skin has no slideshow file at all? There is nothing to modify and
   nothing to ask; 001/FR-015's existing failure notification applies unchanged.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Before modifying any skin file, system MUST ask the user for consent through
  a Yes/No dialog, and MUST NOT modify — or create a backup of — any skin file until the
  user has answered Yes.
- **FR-002**: The dialog MUST tell the user (a) that using the addon requires adding
  integration code to the current skin's SlideShow.xml, so that the addon runs
  automatically when a slideshow starts; (b) where to read exactly what is added and what
  it does — README.md, section "2. Skin integration"; (c) that answering No cancels the
  change and leaves the addon inactive (still enabled in Kodi, but nothing added to the
  skin), and that the same question will be asked again the next time Kodi starts or the
  profile loads; and (d) that to stop being asked, the user should disable or uninstall
  the addon. *(Amended 2026-09-22: (b) was "the exact line that will be added, and that it
  is harmless in nearly all cases".)*
- **FR-003**: **[WITHDRAWN 2026-09-22 — see Clarifications.]** It required the line shown
  in the dialog to be the line the system would actually add. The dialog no longer shows
  the line, so there is nothing left to keep in step.
- **FR-004**: When the user answers Yes, system MUST perform the integration exactly as
  001/FR-015 specifies — backup before the first edit, every resolution variant, no
  duplicates. Consent MUST add no step to, and change no result of, the installation
  itself.
- **FR-005**: When the user answers No, or dismisses the dialog by any means (Back/Esc),
  system MUST NOT modify or back up any skin file, MUST leave the addon enabled in Kodi,
  and MUST ask again at the next profile load where consent is still needed.
- **FR-006**: System MUST show the dialog only when at least one slideshow file of the
  active skin needs the integration added and can be modified. A skin whose every
  slideshow file already carries the integration — including one integrated by an earlier
  version of the addon — MUST NOT trigger a dialog and MUST be left untouched.
- **FR-007**: System MUST NOT remember an answer between profile loads. Each profile load
  re-determines whether consent is needed, so a changed skin, or a skin update that
  removed the integration, triggers the question again.
- **FR-008**: When several slideshow files need the integration, system MUST ask once per
  profile load, and the single answer MUST apply to all of them.
- **FR-009**: The dialog MUST NOT close on its own; it stays until the user answers.
- **FR-010**: System MUST log each consent outcome — asked, accepted, and declined or
  dismissed — to the Kodi log with the "[slideshow-BGM]" header (001/FR-009).
- **FR-011**: Reporting of an install failure MUST remain the non-blocking notification
  and log entry that 001/FR-015 specifies. Only the consent question is a blocking
  dialog.
- **FR-012**: Every string the user sees in this feature MUST be available in each
  language the addon already ships: English, Korean, Spanish and French.

### Key Entities

- **Slideshow File**: One `SlideShow.xml` belonging to the active skin. A skin can ship
  several (one per resolution variant). For consent purposes each is in one of three
  states: *integrated* (carries the addon's line), *needs integration* (lacks it and can
  be modified), or *not modifiable* (missing, unreadable, not writable, or malformed).
- **Consent Request**: The single question asked at most once per profile load, covering
  every slideshow file in the *needs integration* state. Its outcome is Yes, No, or
  dismissed (treated as No). It is never stored.
- **Integration Line**: The one element the addon adds to a slideshow file, documented
  in README.md's section "2. Skin integration". Until 2026-09-22 the dialog showed it
  verbatim; it now points to that section instead.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In 100% of profile loads where a skin needs the integration, the consent
  dialog appears before any skin file changes, and every skin file is byte-identical to
  its pre-load state until the user answers Yes.
- **SC-002**: When the user answers No or dismisses the dialog, 0 skin files are modified,
  0 backup files are created, and the addon is still enabled in Kodi.
- **SC-003**: A user whose skin is already integrated sees 0 dialogs and 0 file changes
  across any number of consecutive profile loads.
- **SC-004**: While the integration is missing and the addon stays enabled, the dialog
  appears at 100% of profile loads; once the addon is disabled or uninstalled, it appears
  at none.
- **SC-005**: A skin with any number of slideshow files needing integration produces
  exactly one dialog per profile load.
- **SC-006**: **[WITHDRAWN 2026-09-22]** The line shown in the dialog was to be
  character-for-character identical to the line written on Yes; the dialog no longer
  shows it.
- **SC-007**: All user-visible text of this feature exists in the addon's four shipped
  languages, with none falling back to a raw string id.

## Assumptions

- **The exact code lives in the README.** A Kodi dialog cannot open a file or follow a
  link, so a user who wants to read the code before answering has to look at the README
  on the repository or in the addon's folder, outside Kodi. Everything the user must know
  in order to decide (FR-002 a, c and d) is in the dialog itself.
- **Modal by design.** The dialog blocks until answered (FR-009) and, being modal, holds
  the user's attention on the Kodi screen until they respond. This is a deliberate
  reversal of 001's "no blocking dialog at login" stance, scoped to the consent question
  only (see Relationship to 001).
- **A file the user cannot act on is not asked about** (Edge Case 2; confirmed by the
  project owner 2026-09-21). Asking consent for a change that cannot succeed would trade
  a real failure for a pointless question on every login; such files keep 001/FR-015's
  notify-and-log path, so consent is requested only after the file's preconditions have
  passed.
- **"Inactive" is a description, not a Kodi state.** After No the addon stays installed
  and enabled; it is inactive only in that nothing launches it. A Kodi-level disable was
  rejected because Kodi would then not run the addon's login-time service at the next
  start, making the promised re-ask impossible until the user re-enables it by hand.
- **No consent store, no "don't ask again" control, no pre-approval setting.** The one
  way to stop the question is the remedy the dialog names: disable or uninstall the
  addon.
- **Removal is out of scope.** This feature only gates *adding* the integration. Removing
  a previously installed integration — including when the user later declines — is not
  part of it.
- **Existing behavior otherwise unchanged.** Skin discovery, precondition checks, backup,
  duplicate avoidance, failure reporting and the run-once nature of the login service all
  remain as specified in 001.
