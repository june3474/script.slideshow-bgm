"""Tests for resources/lib/skinconnector.py (D-007, FR-015)."""

import os
import pathlib
import stat
from typing import Any, Iterator, List, Tuple

import pytest
import xbmc
import xbmcvfs

from resources.lib import skinconnector

world = xbmc.world

HOOK = (
    '<onload condition="System.HasAddon(script.slideshow-bgm) + '
    'System.AddonIsEnabled(script.slideshow-bgm)">RunAddon(script.slideshow-bgm)</onload>'
)
SKIN_DIR_NAME = "skin.testy"

PLAIN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<window id="12345">
  <!-- a skin author's comment -->
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


@pytest.fixture()
def skin_root(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Point ``special://skin/`` at a real, disposable skin directory."""
    root = tmp_path / SKIN_DIR_NAME
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


def _write_xml(path: pathlib.Path, content: str = PLAIN_XML) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _onload_count(path: str) -> int:
    return _read(path).count("RunAddon(script.slideshow-bgm)")


def _errors() -> List[str]:
    return [line for line, level in world.log_lines if level == xbmc.LOGERROR]


def _failure_line(path: str, reason: str, remedy: str) -> str:
    return "[slideshow-BGM] skin hook: install failed at {0} — {1}. Fix: {2}".format(
        path, reason, remedy
    )


# -- is_hooked ---------------------------------------------------------------


def test_is_hooked_is_false_for_an_untouched_skin_file(tmp_path: pathlib.Path) -> None:
    assert skinconnector.is_hooked(_write_xml(tmp_path / "SlideShow.xml")) is False


def test_is_hooked_is_true_for_the_addons_onload(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml", HOOKED_XML)

    assert skinconnector.is_hooked(path) is True


def test_is_hooked_ignores_a_hand_edited_condition(tmp_path: pathlib.Path) -> None:
    path = _write_xml(
        tmp_path / "SlideShow.xml",
        '<window><onload condition="Player.HasAudio">'
        "RunAddon(script.slideshow-bgm)</onload></window>",
    )

    assert skinconnector.is_hooked(path) is True


def test_is_hooked_is_false_for_another_addons_onload(tmp_path: pathlib.Path) -> None:
    path = _write_xml(
        tmp_path / "SlideShow.xml",
        "<window><onload>RunAddon(script.other.addon)</onload></window>",
    )

    assert skinconnector.is_hooked(path) is False


def test_is_hooked_is_false_for_an_unparseable_file(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml", "<window><onload>")

    assert skinconnector.is_hooked(path) is False


def test_is_hooked_is_false_for_a_missing_file(tmp_path: pathlib.Path) -> None:
    assert skinconnector.is_hooked(str(tmp_path / "gone.xml")) is False


# -- install: the happy path -------------------------------------------------


def test_install_adds_the_hook(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")

    assert skinconnector.install(path) is True
    assert skinconnector.is_hooked(path) is True


def test_install_writes_the_contract_element_verbatim(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")

    skinconnector.install(path)

    assert HOOK in _read(path)


def test_install_appends_the_hook_as_the_last_child_of_window(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")

    skinconnector.install(path)

    written = _read(path)
    assert written.index("</controls>") < written.index("RunAddon")
    assert written.index("RunAddon") < written.index("</window>")


def test_install_keeps_the_skins_own_content(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")

    skinconnector.install(path)

    written = _read(path)
    assert "<defaultcontrol>50</defaultcontrol>" in written
    assert 'type="image"' in written
    assert "a skin author's comment" in written


def test_install_preserves_the_skins_own_xml_declaration_style(
    tmp_path: pathlib.Path,
) -> None:
    # Real-world skin files don't all match our own hardcoded declaration --
    # single quotes and lowercase 'utf-8' is what a real Arctic Horizon 2
    # SlideShow.xml uses (found via Tier 2 manual testing).
    original = "<?xml version='1.0' encoding='utf-8'?>\n<window><controls/></window>"
    path = _write_xml(tmp_path / "SlideShow.xml", original)

    skinconnector.install(path)

    assert _read(path).splitlines()[0] == "<?xml version='1.0' encoding='utf-8'?>"


def test_install_uses_a_default_declaration_when_the_original_had_none(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml", "<window><controls/></window>")

    skinconnector.install(path)

    assert _read(path).splitlines()[0] == '<?xml version="1.0" encoding="UTF-8"?>'


def test_install_preserves_a_trailing_newline_when_the_original_had_one(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml", PLAIN_XML)  # PLAIN_XML ends with "\n"

    skinconnector.install(path)

    assert _read(path).endswith("\n")


def test_install_does_not_add_a_trailing_newline_the_original_lacked(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml", PLAIN_XML.rstrip("\n"))

    skinconnector.install(path)

    assert not _read(path).endswith("\n")


def test_uninstall_preserves_the_skins_own_xml_declaration_style(
    tmp_path: pathlib.Path,
) -> None:
    hooked = "<?xml version='1.0' encoding='utf-8'?>\n<window>" + HOOK + "</window>"
    path = _write_xml(tmp_path / "SlideShow.xml", hooked)

    skinconnector.uninstall(path)

    assert _read(path).splitlines()[0] == "<?xml version='1.0' encoding='utf-8'?>"


def test_install_keeps_cjk_content_intact(tmp_path: pathlib.Path) -> None:
    path = _write_xml(
        tmp_path / "슬라이드쇼" / "SlideShow.xml",
        '<window id="1"><label>배경음악 スライドショー</label></window>',
    )

    assert skinconnector.install(path) is True
    assert "배경음악 スライドショー" in _read(path)


def test_install_leaves_no_probe_file_behind_in_the_skin_directory(
    tmp_path: pathlib.Path,
) -> None:
    skin = tmp_path / "1080i"
    path = _write_xml(skin / "SlideShow.xml")

    skinconnector.install(path)

    assert sorted(os.listdir(str(skin))) == ["SlideShow.xml", "SlideShow.xml.original"]


def test_install_logs_the_installation(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")

    skinconnector.install(path)

    assert (
        "[slideshow-BGM] skin hook: installed ({0})".format(path),
        xbmc.LOGINFO,
    ) in world.log_lines


# -- install: backup and idempotency -----------------------------------------


def test_install_backs_the_original_up_before_editing(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    pristine = _read(path)

    skinconnector.install(path)

    assert _read(path + ".original") == pristine


def test_a_second_install_does_not_duplicate_the_hook(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")

    skinconnector.install(path)
    assert skinconnector.install(path) is True

    assert _onload_count(path) == 1


def test_a_second_install_never_overwrites_the_pristine_backup(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    pristine = _read(path)

    skinconnector.install(path)
    skinconnector.install(path)

    assert _read(path + ".original") == pristine
    assert "RunAddon" not in _read(path + ".original")


def test_the_backup_survives_a_skin_update_that_dropped_the_hook(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    pristine = _read(path)
    skinconnector.install(path)

    # Risk R-3: a skin update overwrites the file and takes the hook with it.
    _write_xml(
        tmp_path / "SlideShow.xml",
        '<window id="999"><label>a newer skin release</label></window>',
    )
    skinconnector.install(path)

    assert _read(path + ".original") == pristine


def test_a_second_install_logs_that_the_hook_is_already_present(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")

    skinconnector.install(path)
    skinconnector.install(path)

    assert (
        "[slideshow-BGM] skin hook: already present ({0})".format(path),
        xbmc.LOGDEBUG,
    ) in world.log_lines


def test_install_into_a_file_hooked_by_hand_leaves_it_alone(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_xml(
        tmp_path / "SlideShow.xml",
        '<window><onload condition="Player.HasAudio">'
        "RunAddon(script.slideshow-bgm)</onload></window>",
    )
    before = _read(path)

    assert skinconnector.install(path) is True

    assert _read(path) == before
    assert not os.path.exists(path + ".original")


# -- install: the four preconditions -----------------------------------------


def test_install_reports_a_missing_file(
    tmp_path: pathlib.Path, skin_root: pathlib.Path
) -> None:
    path = str(tmp_path / "gone" / "SlideShow.xml")

    assert skinconnector.install(path) is False
    assert (
        _failure_line(
            path,
            "no SlideShow.xml found under special://skin for skin {0}".format(
                SKIN_DIR_NAME
            ),
            "this skin may not support slideshow integration; try a different skin",
        )
        in _errors()
    )


def test_install_reports_an_unreadable_file(
    tmp_path: pathlib.Path, restore_permissions: None
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    os.chmod(path, 0o000)

    assert skinconnector.install(path) is False
    assert (
        _failure_line(
            path,
            "SlideShow.xml exists but is not readable: {0}".format(path),
            "check file permissions for the user running Kodi",
        )
        in _errors()
    )


def test_install_reports_an_unwritable_file(
    tmp_path: pathlib.Path, restore_permissions: None
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    os.chmod(path, 0o444)

    assert skinconnector.install(path) is False
    assert (
        _failure_line(
            path,
            "SlideShow.xml or its directory is not writable: {0}".format(path),
            "grant write permission, e.g. chmod u+w {0} or edit {0} using sudo, "
            "then restart Kodi".format(path),
        )
        in _errors()
    )


def test_install_reports_an_unwritable_directory(
    tmp_path: pathlib.Path, restore_permissions: None
) -> None:
    skin = tmp_path / "skin"
    path = _write_xml(skin / "SlideShow.xml")
    os.chmod(str(skin), 0o555)

    assert skinconnector.install(path) is False
    assert (
        _failure_line(
            path,
            "SlideShow.xml or its directory is not writable: {0}".format(path),
            "grant write permission, e.g. chmod u+w {0} or edit {0} using sudo, "
            "then restart Kodi".format(path),
        )
        in _errors()
    )


def test_install_reports_unparseable_xml(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml", "<window><onload>oops")

    assert skinconnector.install(path) is False
    assert (
        _failure_line(
            path,
            "SlideShow.xml is not valid XML or has no root <window>: {0}".format(path),
            "the skin file may be corrupted; try reinstalling the skin",
        )
        in _errors()
    )


def test_install_reports_a_file_without_a_window_root(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml", "<includes><include/></includes>")

    assert skinconnector.install(path) is False
    assert (
        _failure_line(
            path,
            "SlideShow.xml is not valid XML or has no root <window>: {0}".format(path),
            "the skin file may be corrupted; try reinstalling the skin",
        )
        in _errors()
    )


def test_a_failed_precondition_writes_nothing(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml", "<window><onload>oops")
    before = _read(path)

    skinconnector.install(path)

    assert _read(path) == before
    assert not os.path.exists(path + ".original")


def test_an_unwritable_file_is_left_untouched(
    tmp_path: pathlib.Path, restore_permissions: None
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    before = _read(path)
    os.chmod(path, 0o444)

    skinconnector.install(path)

    assert _read(path) == before
    assert not os.path.exists(path + ".original")


def test_install_reports_failure_when_write_returns_false_without_raising(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The exact real-Kodi failure mode found via Tier 2 manual testing: a
    # write that silently returns False instead of raising. A production
    # bug once checked only for an exception here and logged a false
    # "installed" success while writing nothing at all.
    path = _write_xml(tmp_path / "SlideShow.xml")
    before = _read(path)

    class _SilentlyFailingHandle:
        def write(self, data: str) -> bool:
            return False

        def close(self) -> None:
            pass

    real_file = xbmcvfs.File

    def fail_only_the_real_write(target: str, mode: str = "r") -> object:
        if mode == "w" and target == path:
            return _SilentlyFailingHandle()
        return real_file(target, mode)

    monkeypatch.setattr(xbmcvfs, "File", fail_only_the_real_write)

    assert skinconnector.install(path) is False
    assert _read(path) == before
    assert (
        _failure_line(
            path,
            "SlideShow.xml or its directory is not writable: {0}".format(path),
            "grant write permission, e.g. chmod u+w {0} or edit {0} using sudo, "
            "then restart Kodi".format(path),
        )
        in _errors()
    )


def test_install_reports_a_file_whose_bytes_are_not_valid_utf8(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "SlideShow.xml"
    path.write_bytes(b"<window><label>\xff\xfe broken bytes</label></window>")

    assert skinconnector.install(str(path)) is False
    assert (
        _failure_line(
            str(path),
            "SlideShow.xml exists but is not readable: {0}".format(path),
            "check file permissions for the user running Kodi",
        )
        in _errors()
    )


def test_install_reports_a_file_that_turns_unwritable_after_the_check(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    before = _read(path)
    real_file = xbmcvfs.File

    def refuse_writes(target: str, mode: str = "r") -> object:
        if mode == "w" and target == path:
            raise OSError("read-only filesystem")
        return real_file(target, mode)

    monkeypatch.setattr(xbmcvfs, "File", refuse_writes)

    assert skinconnector.install(path) is False
    assert _read(path) == before
    assert (
        _failure_line(
            path,
            "SlideShow.xml or its directory is not writable: {0}".format(path),
            "grant write permission, e.g. chmod u+w {0} or edit {0} using sudo, "
            "then restart Kodi".format(path),
        )
        in _errors()
    )


# -- a write that fails after truncating the skin file (D-009) ---------------


def _truncate_then_fail(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    """Make writing ``path`` truncate it and then fail, like a full disk.

    Mode ``"w"`` empties the live skin file the moment it is opened, so this
    is the shape that actually costs a user something: the skin's own
    SlideShow.xml is already gone by the time the write reports failure.
    """
    real_file = xbmcvfs.File

    class _TruncatingFailingHandle:
        def __init__(self, target: str) -> None:
            self._handle = real_file(target, "w")

        def write(self, data: str) -> bool:
            return False

        def close(self) -> None:
            self._handle.close()

    def opener(target: str, mode: str = "r") -> Any:
        if mode == "w" and target == path:
            return _TruncatingFailingHandle(target)
        return real_file(target, mode)

    monkeypatch.setattr(xbmcvfs, "File", opener)


def test_install_restores_the_skin_file_when_the_write_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    before = _read(path)
    _truncate_then_fail(monkeypatch, path)

    assert skinconnector.install(path) is False
    assert _read(path) == before


def test_install_keeps_the_backup_intact_when_the_write_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    before = _read(path)
    _truncate_then_fail(monkeypatch, path)

    skinconnector.install(path)

    assert _read(path + ".original") == before


def test_install_logs_the_rollback_it_performed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    _truncate_then_fail(monkeypatch, path)

    skinconnector.install(path)

    assert any(
        path in line and path + ".original" in line and "restored" in line
        for line in _errors()
    )


def test_install_logs_distinctly_when_the_rollback_itself_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The genuinely bad case: the skin file is truncated and could not be put
    # back, so the log has to name the backup the user must restore by hand.
    path = _write_xml(tmp_path / "SlideShow.xml")
    real_copy = xbmcvfs.copy

    def refuse_to_restore(source: str, destination: str) -> bool:
        if source.endswith(skinconnector.BACKUP_SUFFIX):
            return False
        return bool(real_copy(source, destination))

    monkeypatch.setattr(xbmcvfs, "copy", refuse_to_restore)
    _truncate_then_fail(monkeypatch, path)

    skinconnector.install(path)

    rollback_failures = [
        line
        for line in _errors()
        if path + ".original" in line and "restore" in line and "failed" in line
    ]
    assert rollback_failures
    assert not any("restored it from" in line for line in _errors())


def test_uninstall_restores_the_pristine_skin_file_when_the_write_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # uninstall has the same truncate-then-fail exposure, and the backup
    # install left behind is exactly the file it was trying to get back to.
    path = _write_xml(tmp_path / "SlideShow.xml")
    skinconnector.install(path)
    _truncate_then_fail(monkeypatch, path)

    assert skinconnector.uninstall(path) is False
    assert _read(path) == PLAIN_XML
    assert skinconnector.is_hooked(path) is False


def test_uninstall_logs_the_rollback_it_performed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    skinconnector.install(path)
    _truncate_then_fail(monkeypatch, path)

    skinconnector.uninstall(path)

    assert any(
        path in line and path + ".original" in line and "restored" in line
        for line in _errors()
    )


def test_uninstall_says_so_when_a_failed_write_has_no_backup_to_restore_from(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml", HOOKED_XML)
    _truncate_then_fail(monkeypatch, path)

    assert skinconnector.uninstall(path) is False
    assert any(
        path in line and "no" in line and path + ".original" in line
        for line in _errors()
    )


# -- assess: classify a file without modifying it (specs/002, D-017) ---------


def test_assess_says_a_plain_file_needs_integration(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")

    state = skinconnector.assess(path)

    assert state is skinconnector.SlideshowFileState.NEEDS_INTEGRATION


def test_assess_says_a_hooked_file_is_integrated(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml", HOOKED_XML)

    state = skinconnector.assess(path)

    assert state is skinconnector.SlideshowFileState.INTEGRATED


def test_assess_counts_a_hand_edited_condition_as_integrated(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_xml(
        tmp_path / "SlideShow.xml",
        '<window><onload condition="Player.HasAudio">'
        "RunAddon(script.slideshow-bgm)</onload></window>",
    )

    state = skinconnector.assess(path)

    assert state is skinconnector.SlideshowFileState.INTEGRATED


def test_assess_logs_that_an_integrated_file_already_has_the_hook(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml", HOOKED_XML)

    skinconnector.assess(path)

    assert (
        "[slideshow-BGM] skin hook: already present ({0})".format(path),
        xbmc.LOGDEBUG,
    ) in world.log_lines


UNMODIFIABLE_KINDS = [
    "missing",
    "unreadable",
    "not valid utf-8",
    "unwritable file",
    "unwritable directory",
    "unparseable",
    "no window root",
]


def _unmodifiable_file(kind: str, tmp_path: pathlib.Path) -> Tuple[str, str, str]:
    """Build one way a slideshow file fails the install preconditions.

    Returns the file's path with the reason and remedy that
    contracts/skin-integration.md names for that failure.
    """
    unwritable = (
        "SlideShow.xml or its directory is not writable: {0}",
        "grant write permission, e.g. chmod u+w {0} or edit {0} using sudo, "
        "then restart Kodi",
    )
    unparseable = (
        "SlideShow.xml is not valid XML or has no root <window>: {0}",
        "the skin file may be corrupted; try reinstalling the skin",
    )
    if kind == "missing":
        path = str(tmp_path / "gone" / "SlideShow.xml")
        return (
            path,
            "no SlideShow.xml found under special://skin for skin {0}".format(
                SKIN_DIR_NAME
            ),
            "this skin may not support slideshow integration; try a different skin",
        )
    if kind == "unreadable":
        path = _write_xml(tmp_path / "SlideShow.xml")
        os.chmod(path, 0o000)
    elif kind == "not valid utf-8":
        path = str(tmp_path / "SlideShow.xml")
        (tmp_path / "SlideShow.xml").write_bytes(b"<window>\xff\xfe</window>")
    elif kind == "unwritable file":
        path = _write_xml(tmp_path / "SlideShow.xml")
        os.chmod(path, 0o444)
    elif kind == "unwritable directory":
        path = _write_xml(tmp_path / "skin" / "SlideShow.xml")
        os.chmod(str(tmp_path / "skin"), 0o555)
    else:
        broken = {
            "unparseable": "<window><onload>oops",
            "no window root": "<includes><include/></includes>",
        }
        path = _write_xml(tmp_path / "SlideShow.xml", broken[kind])
    if kind in ("unreadable", "not valid utf-8"):
        return (
            path,
            "SlideShow.xml exists but is not readable: {0}".format(path),
            "check file permissions for the user running Kodi",
        )
    reason, remedy = unwritable if kind.startswith("unwritable") else unparseable
    return path, reason.format(path), remedy.format(path)


@pytest.mark.parametrize("kind", UNMODIFIABLE_KINDS)
def test_assess_marks_an_unmodifiable_file_and_logs_its_reason_and_remedy(
    kind: str,
    tmp_path: pathlib.Path,
    skin_root: pathlib.Path,
    restore_permissions: None,
) -> None:
    # Break named: assess() growing its own copy of install()'s checks and
    # disagreeing with it about what a file is (D-017).
    path, reason, remedy = _unmodifiable_file(kind, tmp_path)

    state = skinconnector.assess(path)

    assert state is skinconnector.SlideshowFileState.NOT_MODIFIABLE
    assert _errors() == [_failure_line(path, reason, remedy)]


@pytest.mark.parametrize(
    "content",
    [PLAIN_XML, HOOKED_XML, "<window><onload>oops"],
    ids=["needs integration", "integrated", "not modifiable"],
)
def test_assess_leaves_the_file_and_its_directory_exactly_as_they_were(
    content: str, tmp_path: pathlib.Path
) -> None:
    # Break named: touching the skin -- a backup, the hook, a stray probe
    # file -- before the user has been asked (spec FR-001).
    skin = tmp_path / "skin"
    path = _write_xml(skin / "SlideShow.xml", content)

    skinconnector.assess(path)

    assert _read(path) == content
    assert os.listdir(str(skin)) == ["SlideShow.xml"]


# -- find_slideshow_xml ------------------------------------------------------


def test_find_slideshow_xml_finds_every_resolution_variant(
    skin_root: pathlib.Path,
) -> None:
    _write_xml(skin_root / "1080i" / "SlideShow.xml")
    _write_xml(skin_root / "16x9" / "SlideShow.xml")

    found = skinconnector.find_slideshow_xml()

    assert sorted(found) == [
        str(skin_root / "1080i" / "SlideShow.xml"),
        str(skin_root / "16x9" / "SlideShow.xml"),
    ]


def test_find_slideshow_xml_matches_the_filename_case_insensitively(
    skin_root: pathlib.Path,
) -> None:
    _write_xml(skin_root / "xml" / "slideshow.xml")
    _write_xml(skin_root / "XML" / "SLIDESHOW.XML")

    assert len(skinconnector.find_slideshow_xml()) == 2


def test_find_slideshow_xml_ignores_other_skin_files(skin_root: pathlib.Path) -> None:
    _write_xml(skin_root / "1080i" / "SlideShow.xml")
    _write_xml(skin_root / "1080i" / "Home.xml")
    _write_xml(skin_root / "1080i" / "SlideShow.xml.original")

    found = skinconnector.find_slideshow_xml()

    assert found == [str(skin_root / "1080i" / "SlideShow.xml")]


def test_find_slideshow_xml_finds_nothing_in_a_skin_without_one(
    skin_root: pathlib.Path,
) -> None:
    _write_xml(skin_root / "1080i" / "Home.xml")

    assert skinconnector.find_slideshow_xml() == []


def test_find_slideshow_xml_finds_nothing_when_the_skin_directory_is_absent(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(xbmcvfs.SPECIAL_ROOTS, "skin", str(tmp_path / "no-such-skin/"))

    assert skinconnector.find_slideshow_xml() == []


def test_every_file_found_can_be_hooked(skin_root: pathlib.Path) -> None:
    _write_xml(skin_root / "1080i" / "SlideShow.xml")
    _write_xml(skin_root / "16x9" / "SlideShow.xml")
    _write_xml(skin_root / "xml" / "slideshow.xml")

    found = skinconnector.find_slideshow_xml()
    assert all(skinconnector.install(path) for path in found)

    assert len(found) == 3
    assert all(skinconnector.is_hooked(path) for path in found)


# -- uninstall ---------------------------------------------------------------


def test_uninstall_removes_the_hook(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    skinconnector.install(path)

    assert skinconnector.uninstall(path) is True
    assert skinconnector.is_hooked(path) is False


def test_uninstall_leaves_every_other_element_untouched(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    skinconnector.install(path)

    skinconnector.uninstall(path)

    written = _read(path)
    assert "<defaultcontrol>50</defaultcontrol>" in written
    assert 'type="image"' in written
    assert "a skin author's comment" in written


def test_uninstall_leaves_another_addons_onload_in_place(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_xml(
        tmp_path / "SlideShow.xml",
        "<window><onload>RunAddon(script.other.addon)</onload></window>",
    )
    skinconnector.install(path)

    skinconnector.uninstall(path)

    assert "RunAddon(script.other.addon)" in _read(path)
    assert "RunAddon(script.slideshow-bgm)" not in _read(path)


def test_uninstall_on_a_file_without_the_hook_is_a_no_op(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml")
    before = _read(path)

    assert skinconnector.uninstall(path) is True
    assert _read(path) == before


def test_uninstall_fails_on_an_unparseable_file(tmp_path: pathlib.Path) -> None:
    path = _write_xml(tmp_path / "SlideShow.xml", "<window><onload>oops")

    assert skinconnector.uninstall(path) is False


def test_uninstall_fails_on_a_missing_file(tmp_path: pathlib.Path) -> None:
    assert skinconnector.uninstall(str(tmp_path / "gone.xml")) is False
