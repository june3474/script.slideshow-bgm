"""Tests for resources/lib/messages.py (contracts/logging.md, D-010)."""

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
