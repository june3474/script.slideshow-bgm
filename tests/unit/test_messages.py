"""Tests for resources/lib/messages.py (contracts/logging.md, D-010)."""

from typing import Any, Dict, List, Tuple

import pytest
import xbmc
import xbmcgui

from resources.lib import messages

world = xbmc.world
dialog_calls = xbmcgui.calls

ADDON_NAME = "Slideshow-BGM"


def test_log_prefixes_the_contract_header() -> None:
    messages.log("session start: source=PLAYLIST:/music/a.m3u shuffle=True")

    assert world.log_lines == [
        ("[slideshow-BGM] session start: source=PLAYLIST:/music/a.m3u shuffle=True", 1)
    ]


def test_log_defaults_to_loginfo() -> None:
    messages.log("BGM start: track=0")

    assert world.log_lines[0][1] == xbmc.LOGINFO


def test_log_passes_the_requested_level_through() -> None:
    messages.log("playlist unreadable", level=xbmc.LOGERROR)
    messages.log("still suspended: next slide is a video clip", level=xbmc.LOGDEBUG)

    assert [level for _, level in world.log_lines] == [xbmc.LOGERROR, xbmc.LOGDEBUG]


def test_log_carries_cjk_text_through_unchanged() -> None:
    messages.log("source=DIRECTORY:/음악/배경음악/강허달림")

    assert world.log_lines == [
        ("[slideshow-BGM] source=DIRECTORY:/음악/배경음악/강허달림", 1)
    ]


def test_notify_shows_a_toast_headed_by_the_addon_name() -> None:
    messages.notify("Background music is unavailable for this slideshow.")

    assert dialog_calls.notifications == [
        (
            ADDON_NAME,
            "Background music is unavailable for this slideshow.",
            xbmcgui.NOTIFICATION_INFO,
        )
    ]


def test_notify_defaults_to_the_informational_icon() -> None:
    messages.notify("continuing without it")

    assert dialog_calls.notifications == [
        (ADDON_NAME, "continuing without it", xbmcgui.NOTIFICATION_INFO)
    ]


def test_notify_passes_an_explicit_icon_straight_through() -> None:
    messages.notify("that playlist is not music", xbmcgui.NOTIFICATION_ERROR)

    assert dialog_calls.notifications == [
        (ADDON_NAME, "that playlist is not music", xbmcgui.NOTIFICATION_ERROR)
    ]


def test_notify_does_not_block_with_a_dialog() -> None:
    messages.notify("continuing without it")

    assert dialog_calls.ok_calls == []
    assert dialog_calls.yesno_calls == []


def test_notify_carries_cjk_text_through_unchanged() -> None:
    messages.notify("배경음악이 비활성화되었습니다.")

    assert dialog_calls.notifications == [
        (ADDON_NAME, "배경음악이 비활성화되었습니다.", xbmcgui.NOTIFICATION_INFO)
    ]


# -- confirm: the one blocking dialog, for the skin-consent question ---------
# (specs/002-skin-hook-consent, D-015)


def test_confirm_is_true_when_the_user_answers_yes() -> None:
    dialog_calls.next_yesno_response = True

    assert messages.confirm("Permission", "Change the skin?") is True


def test_confirm_is_false_when_the_user_answers_no() -> None:
    # Kodi's yesno returns False for No *and* for Back/Esc (D-018), so confirm
    # has nothing to tell them apart with -- and FR-005 wants them identical.
    dialog_calls.next_yesno_response = False

    assert messages.confirm("Permission", "Change the skin?") is False


def test_confirm_shows_the_heading_and_message_it_was_given() -> None:
    messages.confirm("Permission", "Change the skin?")

    assert dialog_calls.yesno_calls == [("Permission", "Change the skin?")]


def test_confirm_never_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    # Break named: adding an autoclose, which would turn "nobody answered"
    # into "No" for someone who was never there to be asked (FR-009).
    seen: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []

    def spy(self: object, *args: Any, **kwargs: Any) -> bool:
        seen.append((args, kwargs))
        return True

    monkeypatch.setattr(xbmcgui.Dialog, "yesno", spy)

    messages.confirm("Permission", "Change the skin?")

    assert len(seen) == 1
    args, kwargs = seen[0]
    assert len(args) == 2
    assert "autoclose" not in kwargs


def test_confirm_defaults_focus_to_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Break named: leaving Kodi's own yesno default (No) in place, so
    # pressing Select the instant the dialog opens declines by default.
    seen: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []

    def spy(self: object, *args: Any, **kwargs: Any) -> bool:
        seen.append((args, kwargs))
        return True

    monkeypatch.setattr(xbmcgui.Dialog, "yesno", spy)

    messages.confirm("Permission", "Change the skin?")

    _, kwargs = seen[0]
    assert kwargs.get("defaultbutton") == xbmcgui.DLG_YESNO_YES_BTN
