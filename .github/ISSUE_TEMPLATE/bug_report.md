---
name: Bug report
about: Something went wrong on a real device
title: ""
labels: bug
---

<!--
This add-on's debugging is entirely log-driven (see CLAUDE.md / research.md
D-008 and Tier 2 of the debug workflow). An issue without a log below just
costs a round-trip asking for one -- please fill in every section.
-->

## Environment

- Kodi version:
- Platform (OS/device):
- Skin:
- Add-on version: <!-- from the issue's "session start: version=..." log line, if it logged -->

## Source configuration

- Source kind: <!-- Playlist or Directory -->
- Format (if Playlist): <!-- .m3u / .pls / .xsp -->

## What happened

<!-- What you expected vs. what actually happened. -->

## Was this the first clip of the slideshow session?

<!-- Yes/No. The video renderer pays a one-time cold-start cost on the first
clip of a session (R-7 in research.md) -- knowing whether this was clip 1
or a later one narrows down which risk this might be. -->

## Log

<!--
1. Enable debug logging: Settings > System > Logging > Enable debug logging
   (and Enable component-specific logging if available), then reproduce the
   issue and restart Kodi or stop/start the slideshow if needed.
2. Locate kodi.log (typically special://logpath, e.g. ~/.kodi/temp/kodi.log
   on Linux).
3. Paste the output of:

     grep '\[slideshow-BGM\]' kodi.log

   below. Include a few lines of surrounding Kodi log context if the
   add-on's own lines don't tell the whole story.
-->

```
paste log output here
```
