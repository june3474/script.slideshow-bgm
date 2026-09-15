"""User-visible and diagnostic message surfaces (FR-009, FR-012, D-010).

The only module in the addon that calls ``xbmc.log`` or constructs an
``xbmcgui.Dialog``; every other module routes through these two functions so
the ``[slideshow-BGM]`` header in contracts/logging.md has exactly one call
site.

There is deliberately no blocking-dialog wrapper. D-010 originally paired one
with :func:`notify` for FR-011's settings-time prompt, but Kodi gives a Script
Mode addon no moment at which to raise it -- the addon's process does not
exist while its settings screen is open -- so every surface this addon can
actually reach is non-blocking (D-010's 2026-09-15 addendum).

Messages arrive here already resolved: callers look their text up from
``resources/language/resource.language.en_gb/strings.po`` by id and format it
before calling in, which keeps this module generic and string-id free.
"""

import xbmc
import xbmcgui

from resources.lib import addon_name

LOG_HEADER = "[slideshow-BGM] "


def log(message: str, level: int = xbmc.LOGINFO) -> None:
    """Emit one Kodi log line carrying the addon's header.

    Args:
        message: Line body, already formatted.
        level: One of Kodi's ``xbmc.LOG*`` constants; defaults to ``LOGINFO``.
    """
    xbmc.log(LOG_HEADER + message, level)


def notify(message: str, icon: str = xbmcgui.NOTIFICATION_INFO) -> None:
    """Show a non-blocking notification headed by the addon name (FR-012).

    Args:
        message: Resolved text to display.
        icon: Kodi notification severity icon; defaults to informational.
    """
    xbmcgui.Dialog().notification(addon_name, message, icon)
