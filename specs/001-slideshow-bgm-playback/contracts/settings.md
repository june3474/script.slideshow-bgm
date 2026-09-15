# Contract: Addon Settings (`resources/settings.xml`)

**Consumers**: the user (via Kodi's addon settings UI), `resources/lib/config.py`

This is the addon's entire user-facing configuration surface. Constitution principle 3.1
forbids configuration through any other channel — no custom config files, environment
variables, or code edits.

Setting ids are a stable contract: `config.py` reads them by id, and changing an id
silently resets that setting for every existing user.

## Settings

| id | Type | Default | Requirement | Semantics |
|---|---|---|---|---|
| `type` | string (spinner) | `Playlist` | FR-005 | `Playlist` \| `Directory` — selects which of the two path settings is live |
| `playlist` | path (file) | `Not Selected` | FR-007 | Masked to `*.m3u\|*.pls\|*.xsp`; visible only when `type` is `Playlist` |
| `directory` | path (folder) | `Not Selected` | FR-006 | Local sources, non-writable; visible only when `type` is `Directory` |
| `random` | boolean (toggle) | `true` | FR-008 | Shuffle. Honored for directory-derived and `.m3u` sources; **ignored** for `.pls`/`.xsp`, which play in native order — the toggle is greyed out in the UI for those (D-011) |
| `on_existing_playback` | string (spinner) | `TakeOver` | FR-014 | `TakeOver` \| `Yield` — what to do when Kodi is already playing audio at slideshow start |

`Not Selected` is the unconfigured sentinel. `config.py` MUST treat it as "no source
configured", not as a path.

### `random` grey-out (D-011)

The `random` toggle is disabled in the settings screen — not just runtime-ignored —
whenever the effective source cannot honor shuffle. This is a settings `<dependencies>`
`enable` condition evaluated by Kodi itself, not addon Python:

```xml
<setting id="random" type="boolean">
  ...
  <dependencies>
    <dependency type="enable">
      <or>
        <condition operator="is" setting="type">Directory</condition>
        <and>
          <condition operator="is" setting="type">Playlist</condition>
          <or>
            <condition operator="contains" setting="playlist">.m3u</condition>
            <condition operator="contains" setting="playlist">.M3U</condition>
          </or>
        </and>
      </or>
    </dependency>
  </dependencies>
</setting>
```

Kodi's dependency system supports exactly four comparison operators — `is`, `lessthan`,
`greaterthan`, `contains` (confirmed against `xbmc/settings/lib/SettingDependency.h` /
`.cpp`) — with no `startswith`/`endswith`, so this checks substring containment against
the full `playlist` path, not a true file-extension match. That is an accepted
imprecision: the worst case is the toggle disagreeing with reality for an unusual path,
which is cosmetic only — FR-008's actual shuffle-ignoring is enforced by `config.py` at
runtime regardless of what this toggle displays.

The outer `<or>` is required: sibling `<dependency>` elements of the same `type` are
combined with **AND**, not OR (source-verified, `CSetting::IsEnabled()` in
`xbmc/settings/lib/Setting.cpp` — it walks every `Enable`-type dependency and clears
`enabled` if any one fails, with no way for a later dependency to re-enable it). Two
top-level `enable` dependencies for mutually-exclusive `type` values (`Directory` vs.
`Playlist`) is therefore an impossible condition that leaves the toggle permanently
disabled — found via Tier 2 step 3 real-Kodi testing (a `Directory` source showed the
toggle greyed out) and fixed by nesting both branches inside one `<or>`.

The `Playlist` branch matches **positively** on `.m3u`/`.M3U`, not negatively on
`.pls`/`.xsp`: real-Kodi testing found the negated form left the toggle wrongly enabled
both for `Not Selected` (contains neither substring) and for `.PLS` — Kodi's
`contains`/`!contains` is case-sensitive with no case-insensitive form (source-verified,
`CSettingDependencyCondition::Check()` in `xbmc/settings/lib/SettingDependency.cpp`, uses
plain `std::string::find`). A positive whitelist fails closed by construction for both
`Not Selected` and any extension case it doesn't explicitly list, instead of failing
open the way the negated blacklist did. `.m3u`/`.M3U` covers the two realistic cases
(all-lowercase, all-uppercase); genuinely mixed-case extensions (`.M3u`) are not covered
and remain the same kind of accepted, cosmetic-only imprecision described above — the
runtime enforcement in `playlist.py` already normalizes case correctly regardless.
See [research.md D-011](../research.md) for the full rationale.

### `playlist` help text carries the Music (Songs) requirement, not a separate row

There is no standalone, always-visible "notice" element in this schema — a
`type="string"` setting with `control type="label"` renders nothing at all in the addon
settings dialog on real Kodi, and `type="lsep"` (a real mechanism elsewhere) is a
`settings version` 1-only token the `version="2"` deserializer this file uses does not
recognize (source-verified; see [research.md D-011](../research.md)'s 2026-09-15
addendum). The requirement that a `.xsp` playlist be of the Music (Songs) type is
instead folded into `playlist`'s own `help="30021"` string, shown in the info bar at the
bottom of the window while that row has focus — which is also hidden automatically
whenever `type` is `Directory`, since the `playlist` row itself already is.

### `on_existing_playback` values

| Value | Behavior |
|---|---|
| `TakeOver` (default) | Stop whatever is playing and start BGM. Preserves FR-001 unconditionally |
| `Yield` | Leave existing playback alone and skip BGM for this slideshow; session goes straight to `DISABLED` |

## Validation contract

`config.py` exposes validation used at exactly one moment, with one surface (D-010, as
amended 2026-09-15):

| Moment | Trigger | Surface | On failure |
|---|---|---|---|
| Slideshow start | Session startup reads settings | **Non-blocking** `Dialog().notification` | Log, notify, continue the slideshow silently (FR-010, FR-012) |

There is deliberately no settings-time row. FR-011 originally specified a blocking
dialog the moment the user picks an unusable source, but a Script Mode addon has no
process running while its own settings screen is open, and Kodi's addon settings dialog
provides no callback for a changed `path` setting — so that surface is unreachable and
was withdrawn (spec.md's 2026-09-15 Clarifications entry; research.md D-010's addendum).
A source the user misconfigures is caught at the next slideshow start instead.

Validation checks, in order:

1. The relevant path setting is not `Not Selected`.
2. `xbmcvfs.exists(path)` — never `os.path.exists()`, which breaks on non-ASCII paths
   under Kodi's ASCII `filesystemencoding` (D-009).
3. For an `.xsp` source only: its root `<smartplaylist type="...">` is `songs` (or the
   legacy `music` alias) — added 2026-09-15 (research.md R-8 addendum) so a
   `movies`/`musicvideos`/`mixed` smart playlist, which can resolve to real playable
   *video* files, is rejected by name (`Reason.NOT_MUSIC_PLAYLIST`) rather than silently
   treated as background music. Checked before check 4 so a wrong-type `.xsp` never
   reaches the `Files.GetDirectory` round-trip at all. This failure gets its own
   error-icon, error-worded notification (`#32005`) at slideshow start, distinct from
   every other reason's generic `#32004` toast.
4. The resolved playlist yields at least one playable entry.

A failure at slideshow start never fails the slideshow itself (FR-010).

## Change propagation

Settings changes take effect on the **next** slideshow, with no Kodi restart (SC-004).
Because each slideshow spawns a fresh Script Mode process, settings are simply re-read at
startup — no invalidation logic is required.

The derived `bgm.m3u` is rebuilt on **every** slideshow start (D-009's 2026-09-15
addendum), so a changed setting and a changed *source* both take effect on the next run.
The mtime cache this used to rely on was removed: it keyed invalidation on `settings.xml`
alone, so a directory whose contents changed kept serving a stale playlist (an SC-005
violation), and measurement showed it was not buying enough to justify that. Rebuilding
is kept cheap by skipping the file write whenever the freshly resolved track list matches
what `bgm.m3u` already holds.

## Localization

Every `label` and `help` attribute references a string id defined in
`resources/language/resource.language.en_gb/strings.po`. No user-visible literal may be
hardcoded in Python.
