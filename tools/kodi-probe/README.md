# BGM Probe

A throwaway Kodi addon that answers the open questions in
[research.md](../../specs/001-slideshow-bgm-playback/research.md) by logging what Kodi actually does. It logs every Player and Monitor callback with +…ms elapsed plus a state snapshot — Slideshow.* conditions, audio/video playing flags, getTime() (which is expected to error once the stream dies — that error is data), Playlist.Position(music), Playlist.Length(music), volume, mute, playing file. A 0.25 s loop emits state-change lines only when a discrete field changes, so the log stays readable.

It has no features and is not part of `script.slideshow-bgm` — install it,
run one slideshow, hand over the log, uninstall it.

The project constitution's quality gates do not apply here: this is a measuring
instrument, not product code.

## What it answers

| Question | Risk | What to look for in the log |
|---|---|---|
| Which callback fires when a clip takes the player, and does the BGM stream die? | D-001 | `onPlayBackStopped` vs `onPlayBackEnded`, and whether `t=` becomes `ERR(...)` |
| Do `Slideshow.*` conditions exist and when do they flip? | D-002, R-4 | `ss[active=… video=… paused=…]` on `state-change` lines |
| Is `Playlist.Position(music)` populated for `.pls` / `.xsp`? | D-005, **R-5** | `music[pos=… len=…]` — `pos=''` means the design's resume path fails |
| How fast is the clip-start callback? | D-003, **R-6** | `+…ms` gap between the last audio state and `onPlayBackStopped` |
| Does any notification fire for the slideshow window? | D-002 | Presence or absence of `onNotification` around slideshow start/end |

## Install

The directory name must match the addon id, so symlink it under Kodi's addon directory
as `script.bgmprobe`:

```bash
ln -s "$PWD/tools/kodi-probe" ~/.kodi/addons/script.bgmprobe
```

Restart Kodi, then enable **BGM Probe** in Settings → Add-ons → My add-ons → Services if
it is not already active. Confirm it is running:

```bash
grep -m1 'PROBE START' ~/.kodi/temp/kodi.log
```

## Run the scenario

Do these in order — the whole point is one continuous log covering all of it.

1. Start a **`.pls` playlist** playing in Kodi's music section — use
   `tests/manual/slideshow-fixtures/playlists/my.pls`, which also covers the D-009
   non-ASCII-filename case. Let a track get past its first few seconds.
2. Without stopping the music, start a **slideshow** over a folder that mixes images with
   at least **two video clips**, ideally with two clips back to back — use
   `tests/manual/slideshow-fixtures/slideshow-source/`.
3. Let it run through every clip and at least a few images.
4. Exit the slideshow with the normal exit action.
5. Repeat steps 1–4 with an **`.xsp`** smart playlist — use
   `tests/manual/slideshow-fixtures/playlists/my.xsp` (requires `tests/manual/slideshow-fixtures/bgm-source/` to be
   scanned into Kodi's music library first, since smart playlists query the library, not
   the filesystem). `.xsp` is the format most likely to behave differently.

Leave Kodi running afterwards, or stop it — either is fine, the log is already written.

## Hand over the log

```bash
cp ~/.kodi/temp/kodi.log /tmp/kodi-probe-run.log
```

Then point Claude at `~/.kodi/temp/kodi.log` (or the copy). Probe lines are greppable on
their own:

```bash
grep '\[BGM-PROBE\]' ~/.kodi/temp/kodi.log
```

Keep the full log rather than only the probe lines — Kodi's own messages around the
slideshow window are part of the evidence.

## Uninstall

```bash
rm ~/.kodi/addons/script.bgmprobe
```

Restart Kodi. Nothing else is left behind: the probe writes no settings, no files, and no
state outside the log.

## Line format

```text
[BGM-PROBE] +12345ms onAVStarted   ss[active=1 video=0 paused=0] play[audio=1 video=0 t=3.20] music[pos='2' len='14'] vol=85 muted=False file='/music/x.mp3'
```

`+…ms` is elapsed time since the probe started, for measuring gaps between callbacks.
`state-change` lines come from a 0.25 s sampling loop and are emitted only when one of the
discrete fields changes, so the log stays readable. Elapsed playback time is deliberately
excluded from change detection — it would fire every tick.
