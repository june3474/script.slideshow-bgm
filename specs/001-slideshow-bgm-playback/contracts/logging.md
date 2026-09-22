# Contract: Kodi Log Output

**Consumers**: users and support reading `~/.kodi/temp/kodi.log`

**Requirement**: FR-009. **Constitution**: principle 4.1 — a Script Mode addon has no
persistent UI, so the Kodi log is its only diagnostic surface.

## Line format

```text
[slideshow-BGM] <message>
```

The header is exactly `[slideshow-BGM]` — capital `BGM`, as FR-009 specifies, and the
casing is part of the contract because users grep for it. It MUST be emitted by a single
wrapper in `resources/lib/messages.py` rather than by scattered `xbmc.log()` calls.

## Levels

| Level | Used for |
|---|---|
| `xbmc.LOGDEBUG` | Per-step detail — individual fade steps, state-machine transitions |
| `xbmc.LOGINFO` | Lifecycle events required by FR-009 |
| `xbmc.LOGWARNING` | Degraded but handled: track index unreadable, hook file not writable |
| `xbmc.LOGERROR` | Operation failed: playlist unreadable, skin XML unparseable, JSON-RPC volume read rejected |

Kodi's default log level suppresses `LOGDEBUG`, which is what keeps per-fade-step output
from flooding the log — a 1-second ramp emits a line per step. Nothing that fires more
than once per transition may be logged above `LOGDEBUG`.

## Required events

FR-009 names slideshow start/end, BGM pause/resume, and errors. Each MUST appear
exactly once per occurrence, at `LOGINFO` or above:

| Event | Level | Message shape |
|---|---|---|
| Session start | `LOGINFO` | `session start: source=<kind>:<path> shuffle=<bool>` |
| BGM disabled for this session | `LOGINFO` | `BGM disabled: <reason>` |
| BGM started | `LOGINFO` | `BGM start: track=<index>` |
| BGM suspended for a video clip | `LOGINFO` | `BGM suspended for video clip at track=<index>` |
| BGM resumed after a video clip | `LOGINFO` | `BGM resume: track=<index> (was <index-1>)` |
| Still suspended (next slide is another clip) | `LOGDEBUG` | `still suspended: next slide is a video clip` |
| Track list derived for a directory/`.pls`/`.xsp` source | `LOGDEBUG` | `resolved <count> tracks from <path> in <n.n> ms` |
| Session end | `LOGINFO` | `session end: reason=<slideshow_closed\|abort_requested> volume restored to <n>` |
| Track index unreadable | `LOGWARNING` | `Playlist.Position(music) unreadable; resuming from playlist start` |
| Skin consent requested *(2026-09-21, specs/002)* | `LOGINFO` | `skin hook: consent requested for <n> file(s)` |
| Skin consent granted *(specs/002)* | `LOGINFO` | `skin hook: consent granted` |
| Skin consent declined or dismissed *(specs/002)* | `LOGINFO` | `skin hook: consent declined or dismissed — skin left untouched; will ask again at next profile load` |
| Skin hook installed | `LOGINFO` | `skin hook: installed (<path>)` |
| Skin hook already present | `LOGDEBUG` | `skin hook: already present (<path>)` |
| Skin hook install failed | `LOGERROR` | `skin hook: install failed at <path> — <reason>. Fix: <remedy>` |

The `resolved … in <n.n> ms` line (added 2026-09-15) exists because D-009's derived-
playlist mtime cache was removed in favour of re-resolving on every slideshow start: the
measurements that justified that were synthetic and from a single machine, so this line
is how a genuinely slow real-world source — a huge directory on slow storage, or a
sluggish `.xsp` query — becomes visible in `kodi.log` instead of being guessed at. It is
`LOGDEBUG` precisely because it fires on every start and must not add noise by default.

`session end` MUST be logged on **every** exit path, including exceptional ones, and MUST
report the restored volume — that line is the evidence for the D-003 invariant that the
user's volume is never left altered.

**Skin hook install failed** (FR-015, added 2026-09-11) carries the load its notification
can't: `<reason>` names the specific precondition that failed and `<path>`; `<remedy>` is
one short, actionable sentence — see
[skin-integration.md](./skin-integration.md#preconditions-for-install) for the fixed set
of reason/remedy pairs. The notification shown to the user is deliberately generic and
points here.

## Prohibited content

Per the constitution's Security section, no secrets in logs. This addon handles none;
the standing rule is that only local media paths, track indices, and volume levels are
logged. Full user media paths are logged at `LOGINFO` (they are already
visible throughout Kodi's own log) but never at a level users are asked to share
publicly beyond that.

## Relationship to user-facing dialogs

Logging is orthogonal to the dialogs in [settings.md](./settings.md) and
[research.md D-010](../research.md): FR-012's notification is emitted **in addition to**
the log line, never instead of it. A user who dismisses a toast must still be able to
find the cause in the log.
