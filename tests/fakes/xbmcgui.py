"""Hand-written fake of the `xbmcgui` module for pytest (research.md D-008).

Only ``Dialog`` is modeled -- the surface ``resources/lib/messages.py``
(D-010) actually calls. Every call is recorded so tests can assert on the
blocking-vs-non-blocking split FR-011/FR-012 require without a display.
"""
from typing import List, Tuple

NOTIFICATION_INFO = "info"
NOTIFICATION_WARNING = "warning"
NOTIFICATION_ERROR = "error"


class _DialogCalls:
    """Recorder shared by every ``Dialog()`` instance, reset per test."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.yesno_calls: List[Tuple[str, str]] = []
        self.ok_calls: List[Tuple[str, str]] = []
        self.notifications: List[Tuple[str, str, str]] = []
        self.next_yesno_response: bool = True


calls = _DialogCalls()


class Dialog:
    """Fake of ``xbmcgui.Dialog``. Blocking dialogs return a test-settable
    canned response instead of waiting on real user input."""

    def yesno(self, heading: str, message: str, **kwargs: object) -> bool:
        calls.yesno_calls.append((heading, message))
        return calls.next_yesno_response

    def ok(self, heading: str, message: str) -> bool:
        calls.ok_calls.append((heading, message))
        return True

    def notification(
        self,
        heading: str,
        message: str,
        icon: str = NOTIFICATION_INFO,
        time: int = 5000,
        sound: bool = True,
    ) -> None:
        calls.notifications.append((heading, message, icon))
