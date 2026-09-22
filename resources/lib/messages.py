"""User-visible and diagnostic message surfaces (FR-009, FR-012, D-010).

The only module in the addon that calls ``xbmc.log`` or constructs an
``xbmcgui.Dialog``; every other module routes through these functions so the
``[slideshow-BGM]`` header in contracts/logging.md has exactly one call site.

Every surface is non-blocking except :func:`confirm`, which exists for one
question only: consent to modify a third-party skin file (specs/002 D-015).
D-010 had originally paired a blocking wrapper with :func:`notify` for
FR-011's settings-time prompt, but Kodi gives a Script Mode addon no moment at
which to raise it -- the addon's process does not exist while its settings
screen is open -- so that wrapper was removed (D-010's 2026-09-15 addendum).
The login-time service, by contrast, is running and can wait for an answer.

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


def confirm(heading: str, message: str) -> bool:
    """Ask a blocking Yes/No question and wait for the answer (specs/002 D-015).

    Passes no ``autoclose``, so the dialog waits for a person rather than
    answering for one (FR-009). Kodi's ``yesno`` returns ``False`` for Back and
    Esc as well as for No (D-018); they are deliberately not told apart.
    Focus defaults to Yes (``defaultbutton``, D-020) rather than Kodi's own
    default of No, since this question is asked precisely because Yes is
    needed for the addon to do anything at all.

    Args:
        heading: Resolved dialog heading.
        message: Resolved dialog body.

    Returns:
        True only when the user chose Yes.
    """
    return bool(
        xbmcgui.Dialog().yesno(
            heading, message, defaultbutton=xbmcgui.DLG_YESNO_YES_BTN
        )
    )
