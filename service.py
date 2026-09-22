"""Run-once service entry point: hook the addon into the active skin (D-007).

Registered at the ``xbmc.service`` extension point so it runs once per Kodi
start/profile login, then exits immediately -- it holds no thread, timer, or
listener, which is what keeps this compatible with constitution principle 2.2
despite registering at the service extension point (justified in plan.md's
Complexity Tracking).

The one thing that can make a run last is the user's answer to the consent
question (specs/002 D-015): every slideshow file is first assessed read-only,
and only if at least one needs the hook is the user asked -- once -- before
anything is modified. The dialog is a synchronous call, so nothing outlives
``main()`` even then.

Before asking, the run waits for the skin's own boot sequence to reach Home
(research.md R-12): a skin that schedules its own splash-to-Home transition
on a timer can have that transition silently dropped by Kodi's window
manager if it lands while our dialog is already open -- confirmed on Arctic
Fuse 2, where the drop is never retried and the skin is left stranded on its
splash screen. Waiting for Home first means no modal exists yet when that
transition is attempted, so the race cannot happen. The wait is abort-aware
(``Monitor.waitForAbort``, D-002's pattern) and capped, so a skin with no
reachable Home state cannot block consent forever.
"""

from typing import List, Tuple

import xbmc

from resources.lib import addon, messages, skinconnector
from resources.lib.skinconnector import SlideshowFileState

STRING_INTEGRATION_FAILED = 32001
STRING_CONSENT_HEADING = 32006
STRING_CONSENT_BODY = 32007

#: Mirrors D-002's session-liveness sampler; not shared code -- service.py
#: and session.py are separate branches of the dependency graph
#: (contracts/modules.md).
WAIT_INTERVAL_SECONDS = 0.5

#: Ceiling on the R-12 wait: a skin with no reachable Home state still gets
#: asked eventually rather than never (fail open, not fail closed).
HOME_WAIT_MAX_SECONDS = 10.0

HOME_ACTIVE_CONDITION = "Window.IsActive(home)"


def _assess_all(paths: List[str]) -> Tuple[List[str], bool]:
    """Assess every slideshow file once, without modifying any.

    Args:
        paths: Every SlideShow.xml the active skin ships.

    Returns:
        The paths that need the hook, in the order given, and whether any file
        could not be modified at all. ``assess`` has already logged the reason
        and remedy for each of those.
    """
    states = {path: skinconnector.assess(path) for path in paths}
    pending = [
        path
        for path, state in states.items()
        if state is SlideshowFileState.NEEDS_INTEGRATION
    ]
    unmodifiable = SlideshowFileState.NOT_MODIFIABLE in states.values()
    return pending, unmodifiable


def _wait_for_home() -> None:
    """Wait for the skin to reach Home before showing the consent dialog.

    Confirmed necessary on real Kodi (research.md R-12): a skin's own
    splash-to-Home transition, if it lands while our dialog is open, is
    refused by the window manager and never retried, stranding the skin on
    its splash screen. Waiting first removes the race instead of guessing at
    a fixed delay. Gives up after :data:`HOME_WAIT_MAX_SECONDS` and logs it,
    so a skin with no reachable Home state is asked anyway.
    """
    monitor = xbmc.Monitor()
    attempts = int(HOME_WAIT_MAX_SECONDS / WAIT_INTERVAL_SECONDS)
    for _ in range(attempts):
        if xbmc.getCondVisibility(HOME_ACTIVE_CONDITION):
            return
        if monitor.waitForAbort(WAIT_INTERVAL_SECONDS):
            return
    messages.log(
        "skin hook: Home never became active after {0}s; asking for "
        "consent anyway".format(HOME_WAIT_MAX_SECONDS),
        xbmc.LOGWARNING,
    )


def _ask_consent(pending: List[str]) -> bool:
    """Ask the user, once, whether the skin may be modified (FR-001, FR-008).

    Args:
        pending: The files that would be modified; only their number is logged.

    Returns:
        True only when the user answered Yes.
    """
    messages.log("skin hook: consent requested for {0} file(s)".format(len(pending)))
    consented = messages.confirm(
        addon.getLocalizedString(STRING_CONSENT_HEADING),
        addon.getLocalizedString(STRING_CONSENT_BODY),
    )
    if consented:
        messages.log("skin hook: consent granted")
    else:
        messages.log(
            "skin hook: consent declined or dismissed — skin left untouched; "
            "will ask again at next profile load"
        )
    return consented


def _install_all(pending: List[str]) -> bool:
    """Install the hook into every file the user agreed to have modified.

    Args:
        pending: The files to hook.

    Returns:
        True when every one of them is hooked afterwards.
    """
    # A list comprehension, not all(generator(...)): every file MUST be
    # attempted even if an earlier one fails (FR-015 -- none may be skipped).
    results = [skinconnector.install(path) for path in pending]
    return all(results)


def main() -> None:
    """Assess the active skin's SlideShow.xml files, ask, and hook them.

    Any failure -- no file found at all, a file that cannot be modified, or an
    ``install()`` rejecting one -- surfaces as exactly one non-blocking
    notification for the whole run (FR-015): skinconnector has already logged
    the specific reason and remedy per file it looked at, so this only decides
    the run's overall verdict.
    """
    paths = skinconnector.find_slideshow_xml()
    if not paths:
        messages.log(
            "skin hook: install failed — no SlideShow.xml found under "
            "special://skin for the active skin. Fix: this skin may not "
            "support slideshow integration; try a different skin",
            xbmc.LOGERROR,
        )
        messages.notify(addon.getLocalizedString(STRING_INTEGRATION_FAILED))
        return
    pending, failed = _assess_all(paths)
    if pending:
        _wait_for_home()
        if _ask_consent(pending) and not _install_all(pending):
            failed = True
    if failed:
        messages.notify(addon.getLocalizedString(STRING_INTEGRATION_FAILED))


if __name__ == "__main__":
    main()
