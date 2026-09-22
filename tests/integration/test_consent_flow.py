"""Skin integration consent -- specs/002-skin-hook-consent, user stories 1-3.

Drives the real ``service.main()`` against real, temporary skin directories, so
what is asserted is what a user's skin actually looks like at each moment: the
one thing replaced is Kodi's blocking Yes/No dialog, whose answer the tests
choose and whose call the spy uses to photograph the skin at the instant the
question is on screen (FR-001, SC-001).

Expectations are derived independently of the code under test: dialog text is
read from the shipped English ``strings.po`` rather than from anything
``service.py`` builds.
"""

import os
import pathlib
import re
import stat
from typing import Any, Callable, Dict, Iterator, List, NamedTuple, Optional, Tuple

import pytest
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

import service
from resources import lib

world = xbmc.world
store = xbmcaddon.store
dialog_calls = xbmcgui.calls

SKIN_NAME = "skin.testy"
ADDON_NAME = "Slideshow-BGM"
HAND_EDITED_HOOK_XML = (
    '<window><onload condition="Player.HasAudio">'
    "RunAddon(script.slideshow-bgm)</onload></window>"
)
LAUNCH_TEXT = "RunAddon(script.slideshow-bgm)"

PLAIN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<window id="12345">
  <defaultcontrol>50</defaultcontrol>
  <controls>
    <control type="image" id="1"/>
  </controls>
</window>
"""

HOOKED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<window id="12345">
  <onload condition="System.HasAddon(script.slideshow-bgm) + \
System.AddonIsEnabled(script.slideshow-bgm)">RunAddon(script.slideshow-bgm)</onload>
</window>
"""

_STRINGS_PO = (
    pathlib.Path(__file__).resolve().parents[2]
    / "resources"
    / "language"
    / "resource.language.en_gb"
    / "strings.po"
)
_ENTRY = re.compile(r'msgctxt "#(\d+)"\nmsgid "((?:[^"\\]|\\.)*)"')

STRING_INTEGRATION_FAILED = 32001
STRING_CONSENT_HEADING = 32006
STRING_CONSENT_BODY = 32007


def _english_strings() -> Dict[int, str]:
    """Every id in the shipped English ``strings.po`` with its real text."""
    text = _STRINGS_PO.read_text(encoding="utf-8")
    return {
        int(string_id): raw.replace("\\n", "\n").replace('\\"', '"')
        for string_id, raw in _ENTRY.findall(text)
    }


# -- fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def english_strings() -> None:
    """Give every string id its real English text, as Kodi would resolve it."""
    store.localized_strings.update(_english_strings())


@pytest.fixture(autouse=True)
def home_already_active() -> None:
    """Most tests exercise the fast path: skip R-12's wait entirely."""
    world.conditions["Window.IsActive(home)"] = True


@pytest.fixture()
def skin_root(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Point ``special://skin/`` at a real, disposable skin directory."""
    root = tmp_path / SKIN_NAME
    root.mkdir()
    monkeypatch.setitem(xbmcvfs.SPECIAL_ROOTS, "skin", str(root) + "/")
    return root


@pytest.fixture()
def restore_permissions(tmp_path: pathlib.Path) -> Iterator[None]:
    """Make every temporary path writable again so cleanup cannot fail."""
    yield
    for root, directories, files in os.walk(str(tmp_path)):
        for name in directories + files:
            target = os.path.join(root, name)
            os.chmod(target, os.stat(target).st_mode | stat.S_IRWXU)
    os.chmod(str(tmp_path), os.stat(str(tmp_path)).st_mode | stat.S_IRWXU)


class Asked(NamedTuple):
    """One appearance of the consent dialog."""

    heading: str
    message: str
    extra: Tuple[Any, ...]
    kwargs: Dict[str, Any]
    skin: Dict[str, bytes]


class DialogSpy:
    """Stands in for Kodi's Yes/No dialog and photographs the skin as it opens."""

    def __init__(self, skin_root: pathlib.Path) -> None:
        self.answer = True
        self.asked: List[Asked] = []
        self.while_open: Optional[Callable[[], None]] = None
        self._skin_root = skin_root

    def snapshot(self) -> Dict[str, bytes]:
        """Every file now under the skin, by relative path, with its bytes."""
        return {
            str(path.relative_to(self._skin_root)): path.read_bytes()
            for path in sorted(self._skin_root.rglob("*"))
            if path.is_file()
        }

    def __call__(self, heading: str, message: str, *extra: Any, **kwargs: Any) -> bool:
        self.asked.append(Asked(heading, message, extra, kwargs, self.snapshot()))
        if self.while_open is not None:
            self.while_open()
        return self.answer


@pytest.fixture()
def dialog(skin_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> DialogSpy:
    """Replace the blocking Yes/No dialog; the answer defaults to Yes."""
    spy = DialogSpy(skin_root)

    def yesno(self: object, heading: str, message: str, *a: Any, **k: Any) -> bool:
        return spy(heading, message, *a, **k)

    monkeypatch.setattr(xbmcgui.Dialog, "yesno", yesno)
    return spy


# -- helpers -----------------------------------------------------------------


def _skin_file(
    skin_root: pathlib.Path, variant: str = "1080i", content: str = PLAIN_XML
) -> pathlib.Path:
    """Write one resolution variant's SlideShow.xml under the skin."""
    path = skin_root / variant / "SlideShow.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _log_lines() -> List[str]:
    return [line for line, _ in world.log_lines]


def _toasts() -> List[Tuple[str, str, str]]:
    return list(dialog_calls.notifications)


# -- User Story 1: understand and approve the skin change --------------------


def test_the_user_is_asked_before_anything_in_the_skin_changes(
    dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    # Break named: installing -- or even backing up -- before asking.
    path = _skin_file(skin_root)
    original = path.read_bytes()

    service.main()

    assert len(dialog.asked) == 1
    # While the question was on screen the skin held exactly its one original,
    # byte for byte: no hook, no .original, no stray probe file (FR-001).
    assert dialog.asked[0].skin == {"1080i/SlideShow.xml": original}


def test_the_dialog_shows_the_shipped_heading_and_body_unaltered(
    dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    # Break named: building the message from anything but the shipped strings
    # -- for instance formatting the body, which no longer has a placeholder.
    _skin_file(skin_root)
    strings = _english_strings()

    service.main()

    asked = dialog.asked[0]
    assert asked.heading == strings[STRING_CONSENT_HEADING]
    assert asked.message == strings[STRING_CONSENT_BODY]


def test_answering_yes_hooks_the_skin_and_keeps_a_pristine_backup(
    dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    path = _skin_file(skin_root)
    original = path.read_bytes()
    dialog.answer = True

    service.main()

    assert _text(path).count(LAUNCH_TEXT) == 1
    assert (path.parent / "SlideShow.xml.original").read_bytes() == original
    assert _toasts() == []


def test_each_stage_of_a_granted_consent_is_logged_once(
    dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    path = _skin_file(skin_root)
    dialog.answer = True

    service.main()

    lines = _log_lines()
    assert (
        lines.count("[slideshow-BGM] skin hook: consent requested for 1 file(s)") == 1
    )
    assert lines.count("[slideshow-BGM] skin hook: consent granted") == 1
    assert lines.count("[slideshow-BGM] skin hook: installed ({0})".format(path)) == 1


# -- User Story 2: decline without side effects ------------------------------

CONSENT_DECLINED_LINE = (
    "[slideshow-BGM] skin hook: consent declined or dismissed — "
    "skin left untouched; will ask again at next profile load"
)


def test_answering_no_leaves_the_skin_exactly_as_it_was(
    dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    # Back and Esc take this same path: Kodi's yesno returns False for them
    # exactly as it does for No (D-018), so there is nothing to tell apart.
    # Break named: hooking or backing up first, or treating a refusal as Yes.
    _skin_file(skin_root)
    before = dialog.snapshot()
    dialog.answer = False

    service.main()

    assert dialog.snapshot() == before


def test_a_declined_consent_is_logged_once_at_info_and_never_as_granted(
    dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    _skin_file(skin_root)
    dialog.answer = False

    service.main()

    assert world.log_lines.count((CONSENT_DECLINED_LINE, xbmc.LOGINFO)) == 1
    assert "[slideshow-BGM] skin hook: consent granted" not in _log_lines()


def test_answering_no_does_not_disable_the_addon(
    dialog: DialogSpy, skin_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Break named: implementing "No" as a Kodi-level disable, which would stop
    # Kodi running this service at the next launch and so make the promised
    # "asked again next login" impossible (D-016).
    _skin_file(skin_root)
    dialog.answer = False
    issued: List[str] = []
    real_json_rpc, real_builtin = xbmc.executeJSONRPC, xbmc.executebuiltin

    def record_json_rpc(request: str) -> Any:
        issued.append(request)
        return real_json_rpc(request)

    def record_builtin(command: str, *rest: Any) -> Any:
        issued.append(command)
        return real_builtin(command, *rest)

    monkeypatch.setattr(xbmc, "executeJSONRPC", record_json_rpc)
    monkeypatch.setattr(xbmc, "executebuiltin", record_builtin)

    service.main()

    assert not [
        call
        for call in issued
        if "SetAddonEnabled" in call or "DisableAddon" in call or "EnableAddon" in call
    ]


def test_after_no_the_next_login_asks_again_and_still_touches_nothing(
    dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    # Break named: remembering the answer -- a stored "declined" flag would
    # silence the very question the user was told would return (FR-005/007).
    _skin_file(skin_root)
    before = dialog.snapshot()
    dialog.answer = False

    service.main()
    service.main()

    assert len(dialog.asked) == 2
    assert dialog.snapshot() == before
    assert world.log_lines.count((CONSENT_DECLINED_LINE, xbmc.LOGINFO)) == 2


# -- User Story 3: no interruption where no consent is needed ----------------


def _failure_toasts() -> List[Tuple[str, str, str]]:
    """The one generic failure notification 001/FR-015 specifies, as shown."""
    text = _english_strings()[STRING_INTEGRATION_FAILED]
    return [(ADDON_NAME, text, xbmcgui.NOTIFICATION_INFO)]


@pytest.mark.parametrize(
    "content",
    [HOOKED_XML, HAND_EDITED_HOOK_XML],
    ids=["hooked by an earlier version", "condition edited by hand"],
)
def test_an_integrated_skin_is_never_asked_about(
    content: str, dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    # Break named: asking again of someone who already has the integration --
    # for instance everyone who installed 1.0.1 (FR-006, SC-003).
    _skin_file(skin_root, content=content)
    before = dialog.snapshot()

    service.main()

    assert dialog.asked == []
    assert dialog.snapshot() == before
    assert _toasts() == []
    assert [line for line in _log_lines() if "consent" in line] == []


def test_a_skin_update_that_dropped_the_hook_is_asked_about_again(
    dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    # Break named: remembering the Yes, so a dropped hook would be re-installed
    # without the user being asked (FR-007, research.md R-3 in 001).
    path = _skin_file(skin_root)
    service.main()
    assert LAUNCH_TEXT in _text(path)

    _skin_file(skin_root)
    service.main()

    assert len(dialog.asked) == 2
    assert LAUNCH_TEXT in _text(path)


def test_switching_to_an_unintegrated_skin_asks_again(
    dialog: DialogSpy,
    skin_root: pathlib.Path,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _skin_file(skin_root)
    service.main()
    other_skin = tmp_path / "skin.other"
    monkeypatch.setitem(xbmcvfs.SPECIAL_ROOTS, "skin", str(other_skin) + "/")
    other = _skin_file(other_skin)

    service.main()

    assert len(dialog.asked) == 2
    assert LAUNCH_TEXT in _text(other)


def test_no_answer_is_stored_anywhere(
    dialog: DialogSpy,
    skin_root: pathlib.Path,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Break named: a well-meant "remember my choice" -- a setting or a file --
    # which the spec rules out (FR-007): the hook's presence is the record.
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setattr(lib, "profile_dir", str(profile))
    _skin_file(skin_root, "1080i")
    settings_before = dict(store.settings)

    dialog.answer = False
    service.main()
    dialog.answer = True
    service.main()

    assert store.settings == settings_before
    assert list(profile.rglob("*")) == []


def test_several_pending_files_produce_one_question_that_covers_them_all(
    dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    # Break named: asking once per resolution variant (FR-008, SC-005).
    paths = [_skin_file(skin_root, variant) for variant in ("1080i", "720p", "16x9")]

    service.main()

    assert len(dialog.asked) == 1
    assert "[slideshow-BGM] skin hook: consent requested for 3 file(s)" in _log_lines()
    assert all(LAUNCH_TEXT in _text(path) for path in paths)
    assert all((path.parent / "SlideShow.xml.original").exists() for path in paths)


def test_declining_the_one_question_leaves_every_variant_alone(
    dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    for variant in ("1080i", "720p", "16x9"):
        _skin_file(skin_root, variant)
    before = dialog.snapshot()
    dialog.answer = False

    service.main()

    assert len(dialog.asked) == 1
    assert dialog.snapshot() == before


def test_yes_modifies_only_the_files_that_needed_it(
    dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    # Break named: re-processing a file that already carries the hook.
    done = _skin_file(skin_root, "1080i", HOOKED_XML)
    todo = _skin_file(skin_root, "720p")
    done_before = done.read_bytes()

    service.main()

    assert len(dialog.asked) == 1
    assert done.read_bytes() == done_before
    assert not (done.parent / "SlideShow.xml.original").exists()
    assert LAUNCH_TEXT in _text(todo)


def test_no_leaves_a_partly_integrated_skin_exactly_as_it_was(
    dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    # Edge Case 1: files that already carry the hook are never removed.
    _skin_file(skin_root, "1080i", HOOKED_XML)
    _skin_file(skin_root, "720p")
    before = dialog.snapshot()
    dialog.answer = False

    service.main()

    assert dialog.snapshot() == before


def test_a_file_that_cannot_be_modified_is_not_asked_about(
    dialog: DialogSpy, skin_root: pathlib.Path, restore_permissions: None
) -> None:
    # Break named: putting an unanswerable question to the user -- a read-only
    # skin would ask it at every login (Edge Case 2).
    path = _skin_file(skin_root)
    os.chmod(path, 0o444)

    service.main()

    assert dialog.asked == []
    assert _toasts() == _failure_toasts()
    assert any(
        "not writable" in line
        for line, level in world.log_lines
        if level == xbmc.LOGERROR
    )


def test_an_unmodifiable_file_does_not_stop_the_others_being_offered(
    dialog: DialogSpy, skin_root: pathlib.Path, restore_permissions: None
) -> None:
    locked = _skin_file(skin_root, "1080i")
    os.chmod(locked, 0o444)
    open_file = _skin_file(skin_root, "720p")

    service.main()

    assert len(dialog.asked) == 1
    assert "[slideshow-BGM] skin hook: consent requested for 1 file(s)" in _log_lines()
    assert LAUNCH_TEXT in _text(open_file)
    assert LAUNCH_TEXT not in _text(locked)
    assert _toasts() == _failure_toasts()


def test_declining_still_reports_the_file_that_could_not_be_modified(
    dialog: DialogSpy, skin_root: pathlib.Path, restore_permissions: None
) -> None:
    locked = _skin_file(skin_root, "1080i")
    os.chmod(locked, 0o444)
    open_file = _skin_file(skin_root, "720p")
    open_before = open_file.read_bytes()
    dialog.answer = False

    service.main()

    assert open_file.read_bytes() == open_before
    assert _toasts() == _failure_toasts()


def test_a_skin_with_no_slideshow_file_is_not_asked_about(
    dialog: DialogSpy, skin_root: pathlib.Path
) -> None:
    service.main()

    assert dialog.asked == []
    assert _toasts() == _failure_toasts()
    assert any(
        "no SlideShow.xml found" in line
        for line, level in world.log_lines
        if level == xbmc.LOGERROR
    )


def test_a_file_that_turns_read_only_while_the_dialog_is_open_is_caught_at_write_time(
    dialog: DialogSpy, skin_root: pathlib.Path, restore_permissions: None
) -> None:
    # Break named: trusting the assessment made before the dialog instead of
    # re-inspecting when installing (D-017).
    path = _skin_file(skin_root)
    before = path.read_bytes()
    dialog.while_open = lambda: os.chmod(path, 0o444)

    service.main()

    assert path.read_bytes() == before
    assert not (path.parent / "SlideShow.xml.original").exists()
    assert _toasts() == _failure_toasts()


# -- R-12: wait for Home before asking, so a skin's own splash-to-Home -------
# transition never races our modal (research.md R-12)

HOME_NEVER_ACTIVE_WARNING = (
    "[slideshow-BGM] skin hook: Home never became active after 10.0s; "
    "asking for consent anyway"
)


def _wait_for_abort_spy(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    """Replace ``xbmc.Monitor.waitForAbort`` and record every call's timeout."""
    calls: List[float] = []
    real_wait_for_abort = xbmc.Monitor.waitForAbort

    def spy(self: xbmc.Monitor, timeout: float) -> bool:
        calls.append(timeout)
        return bool(real_wait_for_abort(self, timeout))

    monkeypatch.setattr(xbmc.Monitor, "waitForAbort", spy)
    return calls


def test_an_already_integrated_skin_never_waits_for_home(
    dialog: DialogSpy, skin_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Break named: waiting even when nothing is pending, so a skin that never
    # needs the question pays R-12's cost anyway.
    world.conditions["Window.IsActive(home)"] = False
    calls = _wait_for_abort_spy(monkeypatch)
    _skin_file(skin_root, content=HOOKED_XML)

    service.main()

    assert calls == []
    assert dialog.asked == []


def test_home_already_active_skips_the_wait_entirely(
    dialog: DialogSpy, skin_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Break named: waiting even when there is nothing to wait for, delaying
    # the dialog for no reason on a skin that was already at Home.
    calls = _wait_for_abort_spy(monkeypatch)
    _skin_file(skin_root)

    service.main()

    assert calls == []
    assert len(dialog.asked) == 1


def test_a_skin_that_never_reaches_home_is_asked_anyway_after_giving_up(
    dialog: DialogSpy, skin_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Break named: blocking consent forever on a skin with no reachable Home
    # state -- the wait must give up and ask anyway (fail open).
    world.conditions["Window.IsActive(home)"] = False
    calls = _wait_for_abort_spy(monkeypatch)
    _skin_file(skin_root)

    service.main()

    assert len(calls) == 20  # HOME_WAIT_MAX_SECONDS / WAIT_INTERVAL_SECONDS
    assert (HOME_NEVER_ACTIVE_WARNING, xbmc.LOGWARNING) in world.log_lines
    assert len(dialog.asked) == 1


def test_the_wait_stops_the_moment_kodi_asks_to_abort(
    dialog: DialogSpy, skin_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Break named: spinning through the full cap even though Kodi already
    # asked the whole process to shut down.
    world.conditions["Window.IsActive(home)"] = False
    world.abort_requested = True
    calls = _wait_for_abort_spy(monkeypatch)
    _skin_file(skin_root)

    service.main()

    assert len(calls) == 1
    assert (HOME_NEVER_ACTIVE_WARNING, xbmc.LOGWARNING) not in world.log_lines
