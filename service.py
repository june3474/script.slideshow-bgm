"""Run-once service entry point: hook the addon into the active skin (D-007).

Registered at the ``xbmc.service`` extension point so it runs once per Kodi
start/profile login, then exits immediately -- it holds no thread, timer, or
listener, which is what keeps this compatible with constitution principle 2.2
despite registering at the service extension point (justified in plan.md's
Complexity Tracking).
"""

import xbmc

from resources.lib import addon, messages, skinconnector

STRING_INTEGRATION_FAILED = 32001


def main() -> None:
    """Install the skin hook into every SlideShow.xml the active skin ships.

    Any failure -- no file found at all, or ``install()`` rejecting one --
    surfaces as exactly one non-blocking notification for the whole run
    (FR-015): skinconnector has already logged the specific reason and remedy
    per file it looked at, so this only decides the run's overall verdict.
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
    # A list comprehension, not all(generator(...)): every file MUST be
    # attempted even if an earlier one fails (FR-015 -- none may be skipped).
    results = [skinconnector.install(path) for path in paths]
    if not all(results):
        messages.notify(addon.getLocalizedString(STRING_INTEGRATION_FAILED))


if __name__ == "__main__":
    main()
