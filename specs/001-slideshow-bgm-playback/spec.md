# Feature Specification: Slideshow Background Music Playback

**Feature Branch**: `001-slideshow-bgm-playback`

**Created**: 2026-09-09

**Status**: Draft

**Input**: User description: "@idea.md" — script.slideshow-bgm: a Kodi addon that plays
background music during image/video slideshows, pausing BGM when a video clip plays
and resuming it when the video ends, until the slideshow itself ends.

## Clarifications

### Session 2026-09-09

- Q: How should the addon notify the user for the alert cases in FR-011 (invalid BGM source picked in settings) and FR-012 (playlist file missing/unreadable at slideshow start)? → A: FR-011 uses a blocking OK dialog (the user is already in the settings UI, so nothing is interrupted); FR-012 uses a non-blocking Kodi notification popup (avoids interrupting an in-progress slideshow/video).
- Q: Should background music transitions (start, pause-for-video, resume-after-video, stop-at-slideshow-end) fade in/out, or cut abruptly? → A: Fade in/out.
- Q: How long should the fade in/out take on each BGM transition? → A: 1 second, matching the existing SC-001/SC-002/SC-003 timing targets.
- Q: If Kodi's music player is already playing something when the slideshow starts, what should the addon do about BGM? → A: Make it a user-configurable addon setting (stop existing playback and play BGM, or leave existing playback untouched and skip BGM), defaulting to "stop existing playback and play BGM".
- **[SUPERSEDED 2026-09-10 — see the next session]** Q: FR-013 mandates a fade on all four transitions, but when a video clip starts the clip takes over playback and the available volume control affects all audio — a fade there would attenuate the clip's own audio. Should it still apply? → A: No. Fades apply only to transitions the addon itself initiates (start, resume, stop); background music goes silent without a fade when a clip begins. FR-013 and SC-002 amended.
- **[SUPERSEDED 2026-09-10 — see the next session]** Q: FR-003 promises resume "from where it was paused" — how exact, and what about playlist formats whose tracks report a length of 0? → A: The same track within a 1-second tolerance for directory and `.m3u` sources. `.pls` and `.xsp` cannot be resumed at a position within a track, so they resume at the beginning of the track following the one that was playing — no elapsed time is recorded for them at all. FR-003 and Assumption 6 amended.
- Q: The spec never says how starting a slideshow launches the addon, yet FR-001 depends on it. → A: The addon integrates itself with the active Kodi skin, installed when the user's profile loads and re-established after a skin change. Added as FR-015 and Edge Case 5.

### Session 2026-09-10

Two answers from the 2026-09-09 session are **superseded** here.

- Q: (supersedes the 2026-09-09 fade answer) Should the fade apply to all four transitions after all? → A: Yes. Every transition fades over 1 second. At a video clip's start the fade necessarily applies to the clip's *incoming* audio rather than to background music, because background music has already been displaced by the clip and cannot be faded out. The clip's audio is deliberately not faded out at its end, which would require watching the clip's remaining time. FR-013 and SC-002 amended.
- Q: (supersedes the 2026-09-09 resume answer) Should same-track position resume be kept for `.m3u` and directory sources? → A: No. Every BGM source now resumes at the beginning of the following track, which removes the position sampler entirely and keeps behavior uniform across formats. The remainder of an interrupted track is skipped. FR-003, Assumption 6 and User Story 2 amended.
- Q: Should the addon become a service-type addon to avoid editing the skin? → A: No. It stays a Script Mode addon launched by a skin hook. A service would have to poll for slideshow start for the entire Kodi session and would put the start-latency budget out of reach, trading a one-time reversible file edit for a permanent background cost. Rationale recorded in research.md D-007.

### Session 2026-09-11

- Q: SC-001, SC-002 and SC-003 each allow 1 second end to end, but FR-013's fade alone is 1 second — leaving nothing for detection, playback startup, or the fade itself to finish. What should the budget be? → A: Relax all three to 2 seconds. The fade stays at 1 second; the extra second covers slideshow-end detection latency (up to 0.5 s) and playback startup, and still leaves headroom. SC-001, SC-002 and SC-003 amended.
- Q: If installing the skin integration fails — most likely a Linux/macOS permission problem — should the addon show a dialog? → A: No, a blocking dialog is too intrusive for something happening at profile login. A non-blocking notification is enough to tell the user something failed and to check the log; the log itself carries the specific reason and a brief suggested remedy. FR-015 amended.

### Session 2026-09-12

- Q: FR-013's fades ramp toward a volume level, but nothing said which level that is if the user manually changes Kodi's volume mid-slideshow — should the addon track a level captured once at slideshow start, or the user's latest deliberate change? → A: The user's latest deliberate change. A fade or the slideshow-end restore MUST NOT silently undo a volume adjustment the user made during playback. FR-016 added.
- Q: If the active skin provides more than one `SlideShow.xml`-equivalent file across its resolution variants, should the addon integrate into just one, or all of them? → A: All of them — none may be left un-integrated. FR-015 amended.
- Q: A handful of `checklists/risk.md` items flagged remaining ambiguity — worth fixing before `/speckit-tasks`? → A: Fix the cheap ones. User Story 1's Independent Test now cites SC-001's 2-second bound explicitly rather than "shortly after"; FR-003 now states that a single-track BGM playlist resumes into itself; FR-012 and Edge Case 2 now cover a directory BGM source becoming invalid at slideshow start, not only a playlist file; SC-004 now states that a mid-slideshow setting change does not affect the session already in progress.

### Session 2026-09-15

One answer from the 2026-09-09 session is **superseded** here.

- Q: (supersedes the 2026-09-09 FR-011 answer) FR-011 requires a blocking dialog the
  moment the user picks an invalid BGM source in the settings screen. How is that
  triggered? → A: It cannot be. Kodi runs a Script Mode addon only when something
  launches it; while the user is in the addon's settings screen there is no addon
  process alive, and Kodi's addon settings dialog offers no callback for a changed
  `path` setting (the only in-dialog hook is a `type="action"` button the user must
  click deliberately, and `Monitor.onSettingsChanged` reaches resident services only —
  which constitution principle 2.2 and research.md D-007 both forbid this addon from
  becoming). FR-011's blocking surface is therefore withdrawn rather than deferred:
  validation runs at slideshow start and reports through FR-012's non-blocking
  notification. The `config.prompt_until_valid()` implementation of the withdrawn
  behavior, which no production code path could ever reach, was removed along with
  `messages.ok`/`messages.yesno` and strings #32002/#32003. FR-011, Edge Case 1,
  research.md D-010 and the module contracts were amended to match.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Background Music Plays During a Slideshow (Priority: P1)

A user starts a Kodi slideshow that contains only images. Background music plays
automatically for the duration of the slideshow, using the music source the user
already configured, so the slideshow isn't silent.

**Why this priority**: This is the addon's core value — without it, the addon does
nothing. Every other behavior (pausing for video, source selection) only matters
once music reliably plays during a slideshow.

**Independent Test**: Configure a BGM source, start an image-only slideshow, and
confirm music starts playing within 2 seconds of the slideshow starting (SC-001) and
stops when the slideshow ends. Delivers standalone value even with no other stories
implemented.

**Acceptance Scenarios**:

1. **Given** a valid BGM source is configured, **When** the user starts a slideshow,
   **Then** background music begins playing.
2. **Given** background music is playing during a slideshow, **When** the slideshow
   ends (naturally or the user exits it), **Then** background music stops.
3. **Given** no BGM source is configured, **When** the user starts a slideshow,
   **Then** the slideshow proceeds normally with no background music and no error
   shown to the user.

---

### User Story 2 - BGM Pauses and Resumes Around Video Clips (Priority: P2)

While a slideshow (mixing images and video clips) is playing with background music,
a video clip begins. The background music automatically pauses so it doesn't overlap
with the video's own audio, then automatically resumes once the video ends. This
repeats for every video clip until the slideshow itself ends.

**Why this priority**: This is what distinguishes the addon from simply playing a
music playlist alongside a slideshow — it's the behavior that makes BGM safe to use
in slideshows that include video clips with their own sound.

**Independent Test**: Configure a BGM source and start a slideshow that includes at
least one video clip among the images. Confirm BGM pauses when the video clip starts
and resumes when it ends, independent of whether Story 3's configuration options are
implemented.

**Acceptance Scenarios**:

1. **Given** background music is playing during a slideshow, **When** a video clip
   in the slideshow begins playing, **Then** background music pauses.
2. **Given** background music is paused because a video clip is playing, **When**
   that video clip ends, **Then** background music resumes at the beginning of the
   track after the one that was interrupted.
3. **Given** a slideshow contains multiple video clips in sequence with no image
   between them, **When** each video clip starts and ends, **Then** background music
   pauses at the first video clip and stays paused across all of them — it does not
   resume between consecutive video clips — only resuming once the slideshow
   advances to an image.

---

### User Story 3 - User Configures the BGM Source (Priority: P3)

A user opens the addon's settings and chooses where their background music comes
from — either a specific playlist file or a directory of music files — and whether
playback order is shuffled. The next slideshow they start uses that configuration.

**Why this priority**: Story 1 already needs *some* configured source to be
testable; this story is what lets a user actually set and change that source rather
than relying on a hardcoded default, so it's valuable but not required to prove out
the core playback behavior.

**Independent Test**: Change the BGM source in the addon's settings screen (directory
vs. playlist file, shuffle on/off), start a slideshow, and confirm the music played
matches the new configuration.

**Acceptance Scenarios**:

1. **Given** the user opens the addon's settings, **When** they select a directory as
   the BGM source, **Then** the addon recursively scans that directory for supported
   audio files and uses them as the BGM playlist on the next slideshow.
2. **Given** the user opens the addon's settings, **When** they select a playlist
   file (`.m3u`, `.pls`, or `.xsp`) as the BGM source, **Then** the addon uses that
   playlist's contents as BGM on the next slideshow.
3. **Given** the user enables shuffle for a directory-based or `.m3u` BGM source,
   **When** the next slideshow starts, **Then** tracks play in random order.
4. **Given** the user enables shuffle while a `.pls` or `.xsp` playlist is selected,
   **When** the next slideshow starts, **Then** the playlist's own native track order
   is used and shuffle is ignored.
5. **Given** the user enables the setting to stop existing playback when a slideshow
   starts, **When** the user starts a slideshow while other music is already playing
   in Kodi, **Then** that music stops and background music starts instead. **Given**
   the user instead disables that setting, **When** they start a slideshow while
   other music is already playing, **Then** the existing music keeps playing and
   background music does not start for that slideshow.

### Edge Cases

1. What happens when the configured directory or playlist contains no supported audio
  files? **[AMENDED 2026-09-15]** The addon cannot detect this while the user is still
  in the settings screen — it has no process running then (FR-011) — so the problem
  surfaces at the next slideshow start instead: the addon notifies the user
  non-blockingly, logs the specific reason, and the slideshow proceeds normally with
  no background music. Changing the source in settings and starting another slideshow
  is what "picking a different one" looks like in practice.
2. What happens when the configured BGM source — a playlist file or a directory — is
  missing, unreadable, or no longer yields any supported audio at slideshow start? The
  addon notifies the user of the problem (in addition to logging the error), and the
  slideshow proceeds normally with no background music.
3. What happens when the slideshow exits — either because the user explicitly issues
  an exit action, or because it has shown all of its content and its repeat setting
  is off — while background music was playing or paused? The addon's process and all
  of its background threads terminate together with the slideshow, regardless of
  what was currently on screen (image or video) or whether background music was
  playing or paused at that instant; background music does not resume after this
  point. Starting a new slideshow starts a fresh instance of the addon.
4. What happens when two video clips play back-to-back with no images between them?
  Background music stays silent across the whole run of clips and resumes only when an
  image appears, as User Story 2 scenario 3 describes. Richer handling — such as
  resuming briefly between clips — is deferred to a future version.
5. What happens when a skin update overwrites the file carrying the addon's slideshow
  integration? Background music silently stops working for subsequent slideshows until
  the integration is re-established, which the addon does the next time the user's
  profile is loaded. The addon does not watch skin files continuously.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST begin playing background music automatically when a
  slideshow starts, using the user's configured BGM source.
- **FR-002**: System MUST automatically pause background music playback when a video
  clip within the slideshow begins playing.
- **FR-003**: System MUST automatically resume background music playback when a video
  clip within the slideshow ends and the slideshow advances to an image; if the
  slideshow instead advances to another video clip, background music MUST remain
  paused. Resume MUST begin at the start of the track following the one that was
  playing when background music was halted. This applies uniformly to every BGM
  source; system MUST NOT attempt to resume at a position within a track, and the
  remainder of an interrupted track is skipped. If the BGM playlist has only one track,
  "the following track" is that same track, consistent with Assumption 5's loop-back
  behavior.
- **FR-004**: System MUST terminate the addon's process and all of its background
  threads whenever the slideshow exits — whether by an explicit user exit action or
  because it has shown all of its content with its repeat setting off — regardless
  of whether background music was playing or paused at that moment; background music
  MUST NOT resume after the slideshow has exited.
- **FR-005**: Users MUST be able to configure the BGM source, through the addon's
  settings, as either a specific playlist file or a directory of music files.
- **FR-006**: When a directory is configured as the BGM source, system MUST
  recursively scan it for supported audio file formats (`.mp3`, `.wav`, `.ogg`,
  `.wma`, `.flac`, `.aac`, `.m4a`) and build the BGM playlist from the files found.
- **FR-007**: Users MUST be able to select a playlist file in `.m3u`, `.pls`, or
  `.xsp` format as the BGM source.
- **FR-008**: Users MUST be able to enable shuffle (random) playback order for BGM
  sourced from a directory or an `.m3u` playlist; shuffle MUST be ignored for `.pls`
  and `.xsp` sources, which play in their own native order.
- **FR-009**: System MUST log key BGM lifecycle events — slideshow start/end, BGM
  pause/resume, and errors — with the header "[slideshow-BGM]" to the Kodi log.
- **FR-010**: If the configured BGM source contains no playable audio, system MUST
  continue the slideshow without background music rather than failing the slideshow.
- **FR-011**: **[AMENDED 2026-09-15 — see the Clarifications entry for that date.]**
  System MUST validate the configured BGM source and tell the user when it cannot be
  used. That notice MUST be delivered at slideshow start via FR-012's non-blocking
  notification: a Script Mode addon has no process running while its settings screen
  is open, so Kodi gives it no moment at which to raise a blocking dialog in response
  to a source the user just picked. System MUST NOT silently accept an unusable source
  — every validation failure is logged, and every one the user configured deliberately
  is also surfaced on screen (FR-012). The originally specified settings-time blocking
  dialog and its cancel-to-disable prompt are withdrawn as unimplementable, not merely
  deferred.
- **FR-012**: When the configured BGM source — a playlist file or a directory — is
  missing, unreadable, or (having passed validation when selected) yields no supported
  audio by slideshow start, system MUST notify the user via a non-blocking notification
  popup (so slideshow playback is not interrupted), in addition to logging the error,
  before continuing the slideshow without background music.
- **FR-013**: System MUST apply a 1-second volume fade to every transition — at
  slideshow start, when a video clip begins, when a video clip ends, and at slideshow
  end — rather than cutting abruptly. At a video clip's start the fade MUST apply to
  the clip's incoming audio, because background music has already been displaced by
  the clip at that point and so cannot itself be faded out. System MUST NOT fade the
  clip's audio out as the clip ends.
- **FR-014**: Users MUST be able to configure, through the addon's settings, whether
  starting a slideshow stops any music already playing in Kodi's player and starts
  BGM, or leaves that existing playback untouched and skips BGM for that slideshow;
  this setting MUST default to stopping existing playback and starting BGM.
- **FR-015**: System MUST integrate itself with the active Kodi skin so that starting
  a slideshow launches background music automatically, with no per-slideshow user
  action. System MUST install that integration without asking the user to edit any
  file by hand, MUST preserve a copy of any skin file it modifies before modifying it,
  MUST NOT duplicate the integration when it is already present, and MUST re-establish
  it after the user changes skins. If the active skin provides more than one such file
  across its resolution variants, system MUST install the integration into every one of
  them — none may be left un-integrated. If the integration cannot be installed — for
  instance because the skin's files are not writable — system MUST notify the user via
  a non-blocking notification that Slideshow-BGM integration failed and that
  details are in the log, MUST log the specific reason together with a suggested
  remedy, and MUST leave Kodi and the slideshow working normally without background
  music. This notification MUST NOT be a blocking dialog: it fires at profile login,
  where nothing else is interrupted, but the user is not necessarily watching.
- **FR-016**: System MUST NOT let a fade or the slideshow-end volume restoration undo a
  deliberate volume change the user makes during playback. The volume level every
  fade-in ramps toward, and the level restored when the slideshow ends, MUST reflect
  the most recently observed volume while background music was last audible — not a
  value captured only once at slideshow start. System MUST re-observe this level
  immediately before background music is next paused for a video clip, and again
  immediately before the slideshow-end fade-out if the slideshow ends while background
  music is still playing.

### Key Entities

- **BGM Source**: The user-selected origin of background music for a slideshow —
  either a playlist file (`.m3u`, `.pls`, `.xsp`) or a directory of audio files —
  together with the user's shuffle preference.
- **Slideshow Session**: One run of a slideshow, from start to when it exits — either
  via an explicit user exit action, or by showing all of its content with its repeat
  setting off (with repeat on, the slideshow continues indefinitely until an
  explicit exit). script.slideshow-bgm's process and background threads live and die
  with this session: they start when the slideshow starts and terminate the moment
  it exits, regardless of what was on screen or of background music's play/pause
  state at that moment.
- **BGM Pause**: A state in which script.slideshow-bgm's process and threads remain
  running but background music playback is halted. It begins whenever the slideshow
  is showing a video clip, and ends either when the slideshow advances to an image
  (background music resumes at the beginning of the following track — FR-003) or when
  the slideshow exits (script.slideshow-bgm terminates without resuming).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Background music reaches normal volume within 2 seconds of a slideshow
  starting, when a valid BGM source is configured. The window covers playback startup
  and the full 1-second fade-in (FR-013).
- **SC-002**: When a video clip begins, background music gives way to it with no
  audible overlap, and the clip's own audio fades in to normal volume over 1 second
  rather than starting abruptly; when the clip ends, background music resumes and
  reaches normal volume within 2 seconds. Both hold across 100% of video transitions
  observed in a slideshow.
- **SC-003**: Background music stops completely within 2 seconds of the slideshow
  ending, with no audio continuing to play afterward. The window covers detection of
  the slideshow ending (up to 0.5 s) and the full 1-second fade-out (FR-013).
- **SC-004**: A user who changes the BGM source or shuffle setting sees that change
  take effect the next time they start a slideshow, without restarting Kodi. A change
  made while a slideshow is already running does not affect that already-running
  session — only the next one started after the change.
- **SC-005**: When a directory is configured as the BGM source, 100% of the files in
  it matching a supported audio format are included in the BGM playlist the next time
  a slideshow starts.

## Assumptions

1. The addon operates only within Kodi's slideshow (Script Mode) context; it is not a
  general-purpose music player invoked independently of a slideshow.
2. Only one slideshow runs at a time per Kodi instance, so only one BGM session needs
  to be tracked at a time.
3. "Video clip" means any video file interspersed with images in the slideshow, played
  through Kodi's own player.
4. Users are expected to have already populated their chosen directory or playlist
  with the music they want played; the addon does not create, edit, or manage music
  libraries beyond generating the derived BGM playlist for directory-based sources.
5. When background music reaches the end of its playlist before the slideshow ends,
  it loops back to the start and continues playing (standard background-music
  behavior), rather than stopping early.
6. Skipping the remainder of an interrupted track (FR-003) is acceptable for
  background music. Users are assumed not to be listening closely enough to a BGM
  playlist to mind losing the tail of one track after a video clip.
7. The slideshow's own repeat/loop setting is controlled by Kodi (or the user)
  independently of this addon; when repeat is enabled, the slideshow does not
  naturally exit after showing all of its content, so in that case the addon exits
  only via an explicit user exit action.
8. FR-003's `.pls`/`.xsp` next-track resume and FR-013's clip-start fade-in each
  assume an unverified Kodi API behavior — respectively, that a specific track in a
  `.pls`/`.xsp` playlist can be targeted for playback, and that the video-clip-start
  callback fires early enough to drop volume before the clip's audio is audible.
  These are recorded as open risks R-5 and R-6 in plan.md, to be confirmed by one run
  of `tools/kodi-probe/` (quickstart.md Tier 2 step 1) before `/speckit-tasks` output
  is treated as final. If either assumption fails, FR-003's `.pls`/`.xsp` clause or
  FR-013's clip-start clause will need to change accordingly.
