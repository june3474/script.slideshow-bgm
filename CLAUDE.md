# CLAUDE.md

Kodi Script Mode addon: plays background music for the duration of a slideshow, stops
for a video clip, resumes after. Built from scratch — no earlier implementation
(`script.service.slideshow-bgm`) is a source of truth for behavior or design; do not
cite or reuse it.

## Architecture, in one paragraph

Kodi exposes one shared player, so a slideshow video clip *destroys* the BGM stream
rather than pausing it — "resume" is stop → remember the following track → replay
(D-001/D-004), with the track index read from `Playlist.Position(music)` inside
`onAVStarted` (D-005). Slideshow start/end emits no event, so liveness is sampled from
an abort-aware `Monitor.waitForAbort(0.5)` loop (D-002). Volume is global, never
per-player, so all four transitions fade over 1s via the `SetVolume` builtin (D-003,
D-013), re-baselined against mid-session user volume changes (D-012). The addon is
launched by an `<onload>` hook injected into the active skin's `SlideShow.xml`, installed
once at login by the service extension point (D-007).

Every design decision rests on one of three bases, each labelled in `research.md`: **API
fact**, **inference**, or **hypothesis** (unverified, must be checked against a running
Kodi before merge).

## Symptom → document map

When a real-device issue comes in, start here instead of re-deriving root cause:

| Symptom | See |
|---|---|
| Playback / resume behavior wrong | D-004, D-006, D-014, R-8 |
| Settings UI (grey-out, validation, notices) | D-011 |
| Volume / fades | D-003, D-012, D-013 |
| Skin integration / launch not firing | D-007 |
| File I/O, directory scan, playlist parsing, caching | D-009 |
| Clip-start timing / renderer cold start (first clip of a session) | R-6, R-7 |

All are in [specs/001-slideshow-bgm-playback/research.md](specs/001-slideshow-bgm-playback/research.md).
`D-xxx` entries are settled decisions; `R-x` entries are open or partially-open risks.

## Quality gates (CI-blocking, zero warnings)

```bash
ruff check .
ruff format --check .
mypy --strict .
pytest
```

All four must pass before a commit lands on `main`.

## Tier 2 bug workflow (real-Kodi issues)

1. **Get the log.** `grep '\[slideshow-BGM\]' kodi.log` (see
   `.github/ISSUE_TEMPLATE/bug_report.md`) plus the addon version the "session start"
   line now carries.
2. **Root-cause via Kodi's C++ source**, not guesswork — the API facts in `research.md`
   were established this way; a new bug usually means either a fact was wrong or a
   hypothesis just got falsified.
3. **Fix with TDD**: reproduce with a failing test against the in-repo fakes
   (`tests/fakes/`, D-008) before touching production code.
4. **Document it**: add a dated addendum to `research.md` (and update `tasks.md` if it
   changes planned work) so the next session doesn't re-derive the same root cause.

## Conventions

- **TDD-first for all implementation work**, not only Tier 2 bug fixes: write a failing
  test against the fakes before writing production code. Tier 2 above is the additional
  cycle a real-device bug goes through on top of this.
- `specs/001-slideshow-bgm-playback/` is the design record — `spec.md` (requirements),
  `plan.md` (architecture), `research.md` (decisions + risks, source of truth for *why*),
  `data-model.md`, `contracts/`, `tasks.md`, `quickstart.md` (gate commands, Tier 1/2
  test breakdown).
- Tests run against hand-written Kodi fakes (`tests/fakes/`, D-008) for Tier 1 (`pytest`)
  and against a real Kodi instance for Tier 2 (manual, see `quickstart.md`).
- Python 3.8 floor (Kodi v20 Nexus) — no 3.9+ syntax (`dict |`, builtin generics at
  runtime, `match`).
- `main` has a GitHub ruleset requiring PRs; pushing directly bypasses it. This is
  intentional (solo repo) — push directly when asked, don't warn about the bypass
  notice GitHub prints.
