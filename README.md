# Slideshow-BGM <img src="https://raw.githubusercontent.com/june3474/script.slideshow-bgm/gh-pages/img/icon50.png" alt="" align="top">

Slideshow-BGM is a Kodi add-on that plays background music while an image or
mixed-media slideshow is running. When the slideshow reaches a video clip, the
add-on keeps the background music out of the way and resumes it when the slideshow
returns to an image.

The add-on is designed for Kodi 20 (Nexus) and newer and has no runtime dependency
outside Kodi.

Feel free to use, modify, and share it.

## Features

- Starts background music automatically with a Kodi slideshow.
- Supports slideshows containing both images and video clips.
- Keeps BGM silent across consecutive video clips and resumes it on the next image.
- Resumes at the beginning of the track after the one interrupted by a video.
- Applies one-second volume fades to slideshow and video transitions without showing
  Kodi's volume OSD.
- Preserves volume changes made by the user during a slideshow.
- Accepts `.m3u`, `.pls`, and Kodi music smart playlists (`.xsp`).
- Recursively scans a directory for `.mp3`, `.wav`, `.ogg`, `.wma`, `.flac`, `.aac`,
  and `.m4a` files.
- Supports shuffle for directory and `.m3u` sources. `.pls` and `.xsp` sources keep
  their own order.
- Lets you either replace music already playing in Kodi or leave it untouched and
  skip BGM for that slideshow.
- Continues the slideshow normally if the configured music source is unavailable.
- Runs only while a slideshow is on screen — nothing stays resident between slideshows.

## Requirements

- Kodi 20 (Nexus) or newer
- A skin containing a `SlideShow.xml` window definition
- A writable active skin directory for automatic integration

The add-on declares `xbmc.python` 3.0.0 and supports all platforms supported by Kodi.

## 1. Installation

### 1-1. Using Git (recommended)

Clone the repository into the `addons` directory inside your
[Kodi data folder](https://kodi.wiki/view/Kodi_data_folder):

```bash
cd ~/.kodi/addons
git clone https://github.com/june3474/script.slideshow-bgm.git
```

The example path is for a typical Linux installation. Use the corresponding Kodi data
folder on Windows, macOS, Android, or another platform. Restart Kodi, then enable
**Slideshow-BGM** from the add-on manager if it is not already enabled.

### 1-2. Installing a ZIP

**Step 1 — enable installation from unknown sources.**

From Kodi's home screen, open the gear icon in the top-left corner:

![Kodi home screen, gear icon](https://raw.githubusercontent.com/june3474/script.slideshow-bgm/gh-pages/img/enable_unknown_source_1.jpg)

Choose **System**:

![Kodi settings, System](https://raw.githubusercontent.com/june3474/script.slideshow-bgm/gh-pages/img/enable_unknown_source_2.jpg)

Select **Add-ons** in the sidebar and turn on **Unknown sources**. Kodi warns you about
the setting; confirm to continue.

![Add-ons settings, Unknown sources](https://raw.githubusercontent.com/june3474/script.slideshow-bgm/gh-pages/img/enable_unknown_source_3.jpg)

*The three pictures above are from
[technadu.com](https://www.technadu.com/enable-unknown-sources-on-kodi/11658/).*

**Step 2 — download the add-on.** Get the `Source code (zip)` of the latest release from
the [releases page](https://github.com/june3474/script.slideshow-bgm/releases).

**Step 3 — install the ZIP.** On Kodi's home screen choose **Add-ons**, click the
'open box' icon in the top-left corner, and select **Install from zip file**. Locate the
file you downloaded and select it.

![Add-ons, Install from zip file](https://raw.githubusercontent.com/june3474/script.slideshow-bgm/gh-pages/img/install_1.jpg)

![Choosing the downloaded ZIP](https://raw.githubusercontent.com/june3474/script.slideshow-bgm/gh-pages/img/install_2.jpg)

Restart Kodi after installing.

## 2. Skin integration

A Kodi script add-on cannot detect slideshow startup by itself. On profile login,
Slideshow-BGM therefore asks your permission (see below) and then adds the following
hook to every `SlideShow.xml` supplied by the active skin:

```xml
<onload condition="System.HasAddon(script.slideshow-bgm) + System.AddonIsEnabled(script.slideshow-bgm)">RunAddon(script.slideshow-bgm)</onload>
```

This is what keeps the add-on running only while a slideshow is on screen, instead of
for the whole time Kodi is up.

The `condition` is a guard: it makes the line do nothing unless Slideshow-BGM is both
installed and enabled. That is why it is harmless in nearly all cases, and why it stays
inert if you later disable or remove the add-on.

Editing a skin file you didn't write is invasive, and that trade-off was made
deliberately, not by default. A background service was considered and rejected: Kodi
emits no event when a slideshow starts, so a service would have to poll for it
continuously for the entire session, whether or not a slideshow is ever opened. The
skin hook instead costs nothing while idle and fires at the instant the slideshow
starts, leaving the full timing budget for playback. A resident service would also
violate the add-on's own constitution, which forbids anything outliving a single
script run. Attaching to the slideshow window directly from Python was also considered
and found technically impossible — Kodi's native slideshow window does not dispatch to
Python callbacks at all.

![The hook added to a skin's SlideShow.xml](https://raw.githubusercontent.com/june3474/script.slideshow-bgm/gh-pages/img/hookup_after.png)

### Asking for your permission

Because this edits a file you didn't write, Slideshow-BGM asks before it touches
anything. When the active skin's `SlideShow.xml` doesn't have the hook yet, a Yes/No
dialog appears at profile login. It says that the add-on needs to add integration code to
the skin's `SlideShow.xml` so that it can run automatically when a slideshow starts, and
points to this section, "2. Skin integration", for the exact code and what it does.

- **Yes** — the hook is added, and background music works from the next slideshow.
- **No** (or Back/Esc) — nothing is changed. The add-on stays installed and enabled but
  does nothing, because nothing launches it, and the question comes back the next time
  Kodi starts or you log in.

To stop being asked, disable or uninstall the add-on. You are not asked if the skin
already has the hook — including one installed by an earlier version of the add-on. You
are asked again if you switch to a skin that doesn't have it, or a skin update removes
it: the add-on never remembers an answer.

Before changing a skin file, the add-on creates a sibling backup with the suffix
`.original`. Repeated startup does not add duplicate hooks. After changing skins,
restart Kodi so the new active skin can be integrated.

Some system-installed skins are read-only for the user running Kodi, particularly the
default skin on Linux. If integration fails, Slideshow-BGM shows a notification and
writes the specific reason and a suggested remedy to `kodi.log`.

![Notification shown when skin integration fails](https://raw.githubusercontent.com/june3474/script.slideshow-bgm/gh-pages/img/integration_failed.jpg)

You can either grant the Kodi user write access to the affected skin file, or install a
skin of your own — skins you install yourself live in your private `addons` directory,
where there is no permission problem — and then restart Kodi.

## 3. Configuration

Open **Slideshow-BGM → Configure** in Kodi's add-on manager and choose a source type.

![Slideshow-BGM settings](https://raw.githubusercontent.com/june3474/script.slideshow-bgm/gh-pages/img/configure_settings.jpg)

### Playlist

Select one of the following:

- `.m3u`
- `.pls`
- `.xsp` — it must be a Kodi **Music (Songs)** smart playlist

![Choosing a playlist file](https://raw.githubusercontent.com/june3474/script.slideshow-bgm/gh-pages/img/configure_playlist.jpg)

Shuffle is available for `.m3u`. A `.pls` or `.xsp` playlist always uses its own
native order, and the **Shuffle** toggle is greyed out for those.

### Directory

Select a directory containing music. It is scanned recursively at the beginning of
every slideshow, so files added later are picked up automatically. The resulting
playlist is stored as `bgm.m3u` in the add-on's folder under Kodi's
[addon_data folder](https://kodi.wiki/view/Userdata#addon_data).

### Existing playback

Choose what happens if Kodi is already playing music when a slideshow begins:

- **Stop it and play background music** — the default.
- **Leave it alone** — preserves the existing playback and disables Slideshow-BGM for
  that slideshow.

Configuration changes take effect the next time a slideshow starts. Kodi does not run
this script while its settings window is open, so an invalid source is reported at
slideshow startup rather than immediately when it is selected.

## 4. Playback behavior

For image-only slideshows, BGM loops until the slideshow closes. In a mixed slideshow:

1. A video clip interrupts the current BGM track.
2. BGM stays silent while that clip, and any immediately following clips, play.
3. When an image appears again, BGM resumes at the beginning of the next track.

The interrupted track is not resumed from its previous timestamp. A single-track
playlist simply starts that same track again.

When the slideshow exits, the add-on stops playback it owns, finishes or cancels its
fade workers, restores the appropriate volume, and exits.

## 5. Troubleshooting

### Background music never starts

- Confirm that a playlist or directory has been selected in the add-on settings.
- Confirm that the source still exists and contains supported music files.
- For `.xsp`, confirm that it is a **Music (Songs)** smart playlist.
- Restart Kodi after installing the add-on or changing skins.
- Look for messages beginning with `[slideshow-BGM]` in `kodi.log`.

On Linux, the log is commonly found at `~/.kodi/temp/kodi.log`:

```bash
grep '\[slideshow-BGM\]' ~/.kodi/temp/kodi.log
```

### Skin integration failed

The active skin may not provide `SlideShow.xml`, or its files may not be readable or
writable. Check the detailed error in `kodi.log`. Installing a skin of your own in the
user add-ons directory is often the simplest solution when a system skin is owned by
root.

### A skin update disables the add-on

A skin update may replace its `SlideShow.xml` and remove the hook. Restart Kodi; the
add-on checks the active skin again at profile login and, after asking your permission
again, reinstalls a missing hook.

### The permission dialog keeps appearing

It returns at every Kodi start or login for as long as the skin lacks the hook and the
add-on is enabled. Answer **Yes** to install the hook, or disable or uninstall
Slideshow-BGM to stop the question.

## 6. Uninstallation

Uninstall Slideshow-BGM from Kodi's add-on manager. The injected hook is guarded by
`System.HasAddon` and `System.AddonIsEnabled`, so it is inert after the add-on is
removed or disabled.

For a completely clean manual removal:

- Delete the Slideshow-BGM `<onload>` element from each modified `SlideShow.xml`. A
  `.original` backup is also created beside each file, but restore it wholesale only if
  the skin file has not received other changes since the backup was made.
- Delete the `script.slideshow-bgm` folder under Kodi's
  [addon_data folder](https://kodi.wiki/view/Userdata#addon_data).

## License

MIT
