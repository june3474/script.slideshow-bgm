"""Tests for resources/lib/config.py (FR-005..FR-008, FR-012, FR-014)."""

import pathlib
from typing import List

import pytest
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources import lib
from resources.lib import config, playlist
from resources.lib.config import Policy, Reason
from resources.lib.playlist import DIRECTORY, PLAYLIST, BgmSource

store = xbmcaddon.store
dialog_calls = xbmcgui.calls

ADDON_NAME = "Slideshow-BGM"


def _playlist_file(tmp_path: pathlib.Path, content: str = "/music/a.mp3\n") -> str:
    path = tmp_path / "my.m3u"
    path.write_text(content, encoding="utf-8")
    return str(path)


# -- read_source -------------------------------------------------------------


def test_read_source_treats_the_sentinel_as_unconfigured() -> None:
    assert store.settings["playlist"] == "Not Selected"

    assert config.read_source() is None


def test_read_source_reads_the_playlist_setting_for_a_playlist_type() -> None:
    store.settings["type"] = "Playlist"
    store.settings["playlist"] = "/music/my.m3u"
    store.settings["directory"] = "/music/ignored"

    assert config.read_source() == BgmSource(
        kind=PLAYLIST, path="/music/my.m3u", shuffle=True
    )


def test_read_source_reads_the_directory_setting_for_a_directory_type() -> None:
    store.settings["type"] = "Directory"
    store.settings["directory"] = "/music/jazz"
    store.settings["playlist"] = "/music/ignored.m3u"

    assert config.read_source() == BgmSource(
        kind=DIRECTORY, path="/music/jazz", shuffle=True
    )


def test_read_source_carries_the_shuffle_setting() -> None:
    store.settings["playlist"] = "/music/my.m3u"
    store.settings["random"] = "false"

    source = config.read_source()

    assert source is not None
    assert source.shuffle is False


def test_read_source_is_unconfigured_when_the_live_path_is_the_sentinel() -> None:
    store.settings["type"] = "Directory"
    store.settings["directory"] = "Not Selected"
    store.settings["playlist"] = "/music/my.m3u"

    assert config.read_source() is None


def test_read_source_is_unconfigured_when_the_path_is_empty() -> None:
    store.settings["playlist"] = ""

    assert config.read_source() is None


def test_read_source_keeps_a_korean_path_intact() -> None:
    store.settings["playlist"] = "/음악/재즈/my.m3u"

    source = config.read_source()

    assert source is not None
    assert source.path == "/음악/재즈/my.m3u"


# -- read_source: FR-008's shuffle-ignoring formats --------------------------


@pytest.mark.parametrize(
    "path", ["/music/mix.pls", "/music/mix.PLS", "/music/smart.xsp", "/music/smart.XSP"]
)
def test_read_source_ignores_shuffle_for_a_pls_or_xsp_playlist(path: str) -> None:
    # FR-008 / US3 scenario 4: these play in their own native order, so the
    # `random` setting being on must not reach the player. D-011's settings-UI
    # grey-out is only an affordance -- this is where the rule is enforced.
    store.settings["type"] = "Playlist"
    store.settings["playlist"] = path
    store.settings["random"] = "true"

    source = config.read_source()

    assert source is not None
    assert source.shuffle is False


@pytest.mark.parametrize("path", ["/music/mix.m3u", "/music/mix.M3U"])
def test_read_source_honors_shuffle_for_an_m3u_playlist(path: str) -> None:
    store.settings["type"] = "Playlist"
    store.settings["playlist"] = path
    store.settings["random"] = "true"

    source = config.read_source()

    assert source is not None
    assert source.shuffle is True


def test_read_source_honors_shuffle_for_a_directory_source() -> None:
    store.settings["type"] = "Directory"
    store.settings["directory"] = "/music/jazz"
    store.settings["random"] = "true"

    source = config.read_source()

    assert source is not None
    assert source.shuffle is True


def test_read_source_honors_shuffle_for_a_directory_named_like_a_playlist() -> None:
    # What gets played is the derived bgm.m3u, not the directory's own name.
    store.settings["type"] = "Directory"
    store.settings["directory"] = "/music/my.xsp"
    store.settings["random"] = "true"

    source = config.read_source()

    assert source is not None
    assert source.shuffle is True


@pytest.mark.parametrize("path", ["/music/mix.m3u", "/music/mix.pls", "/music/mix.xsp"])
def test_read_source_leaves_shuffle_off_for_every_format_when_unset(path: str) -> None:
    store.settings["type"] = "Playlist"
    store.settings["playlist"] = path
    store.settings["random"] = "false"

    source = config.read_source()

    assert source is not None
    assert source.shuffle is False


# -- validate ----------------------------------------------------------------


def test_validate_rejects_the_sentinel_before_touching_the_filesystem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked: List[str] = []

    def spy_exists(path: str) -> bool:
        checked.append(path)
        return True

    monkeypatch.setattr(xbmcvfs, "exists", spy_exists)

    result = config.validate(BgmSource(kind=PLAYLIST, path="Not Selected"))

    assert result.ok is False
    assert result.reason is Reason.NOT_SELECTED
    assert checked == []


def test_validate_rejects_an_empty_path_as_unselected() -> None:
    result = config.validate(BgmSource(kind=PLAYLIST, path=""))

    assert result.reason is Reason.NOT_SELECTED


def test_validate_reports_a_missing_path_before_resolving_it(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolved: List[BgmSource] = []

    def spy_resolve(source: BgmSource) -> str:
        resolved.append(source)
        return "/anything"

    monkeypatch.setattr(playlist, "resolve", spy_resolve)

    result = config.validate(BgmSource(kind=PLAYLIST, path=str(tmp_path / "gone.m3u")))

    assert result.ok is False
    assert result.reason is Reason.MISSING
    assert resolved == []


def test_validate_reports_an_existing_but_unplayable_source_as_empty(
    tmp_path: pathlib.Path,
) -> None:
    result = config.validate(
        BgmSource(kind=PLAYLIST, path=_playlist_file(tmp_path, content=""))
    )

    assert result.ok is False
    assert result.reason is Reason.EMPTY


def test_validate_accepts_a_playlist_file_with_entries(tmp_path: pathlib.Path) -> None:
    result = config.validate(BgmSource(kind=PLAYLIST, path=_playlist_file(tmp_path)))

    assert result.ok is True
    assert result.reason is None


def test_validate_accepts_a_directory_holding_audio(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    music = tmp_path / "음악"
    music.mkdir()
    (music / "강허달림.mp3").write_text("x", encoding="utf-8")

    result = config.validate(BgmSource(kind=DIRECTORY, path=str(music)))

    assert result.ok is True


def test_validate_reports_a_directory_without_audio_as_empty(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    music = tmp_path / "music"
    music.mkdir()
    (music / "cover.jpg").write_text("x", encoding="utf-8")

    result = config.validate(BgmSource(kind=DIRECTORY, path=str(music)))

    assert result.reason is Reason.EMPTY


def test_validate_reports_a_pls_source_with_no_file_entries_as_empty(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    pls = tmp_path / "mix.pls"
    pls.write_text("[playlist]\n", encoding="utf-8")

    result = config.validate(BgmSource(kind=PLAYLIST, path=str(pls)))

    assert result.ok is False
    assert result.reason is Reason.EMPTY


def test_validate_reports_an_xsp_source_whose_json_rpc_call_yields_nothing_as_empty(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    xsp = tmp_path / "smart.xsp"
    xsp.write_text('<smartplaylist type="songs"/>', encoding="utf-8")

    result = config.validate(BgmSource(kind=PLAYLIST, path=str(xsp)))

    assert result.ok is False
    assert result.reason is Reason.EMPTY


def test_validate_rejects_an_xsp_source_that_is_not_a_music_playlist(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    xsp = tmp_path / "smart.xsp"
    xsp.write_text('<smartplaylist type="movies"/>', encoding="utf-8")

    result = config.validate(BgmSource(kind=PLAYLIST, path=str(xsp)))

    assert result.ok is False
    assert result.reason is Reason.NOT_MUSIC_PLAYLIST


def test_validate_rejects_a_non_music_xsp_before_resolving_its_tracks(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ordering (contracts/settings.md): the type check comes before the
    # EMPTY check, so a non-music .xsp is named for what it is rather than
    # costing a Files.GetDirectory round-trip and then being called empty.
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    resolved: List[BgmSource] = []

    def spy_resolve(source: BgmSource) -> str:
        resolved.append(source)
        return "/anything"

    monkeypatch.setattr(playlist, "resolve", spy_resolve)
    xsp = tmp_path / "smart.xsp"
    xsp.write_text('<smartplaylist type="mixed"/>', encoding="utf-8")

    result = config.validate(BgmSource(kind=PLAYLIST, path=str(xsp)))

    assert result.reason is Reason.NOT_MUSIC_PLAYLIST
    assert resolved == []


def test_validate_accepts_a_songs_xsp_that_resolves_to_tracks(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lib, "profile_dir", str(tmp_path / "profile"))
    xsp = tmp_path / "smart.xsp"
    xsp.write_text('<smartplaylist type="songs"/>', encoding="utf-8")
    xbmc.world.xsp_directories[str(xsp)] = [
        {"file": "/music/a.mp3", "filetype": "file"},
    ]

    result = config.validate(BgmSource(kind=PLAYLIST, path=str(xsp)))

    assert result.ok is True
    assert result.reason is None


def test_validate_leaves_a_non_xsp_playlist_untouched_by_the_music_type_check(
    tmp_path: pathlib.Path,
) -> None:
    # An .m3u carries no <smartplaylist> type at all; the new check must not
    # reach it.
    result = config.validate(BgmSource(kind=PLAYLIST, path=_playlist_file(tmp_path)))

    assert result.ok is True


def test_validate_never_raises_a_dialog(tmp_path: pathlib.Path) -> None:
    config.validate(BgmSource(kind=PLAYLIST, path="Not Selected"))
    config.validate(BgmSource(kind=PLAYLIST, path=str(tmp_path / "gone.m3u")))

    assert dialog_calls.yesno_calls == []
    assert dialog_calls.ok_calls == []
    assert dialog_calls.notifications == []


# -- existing_playback_policy ------------------------------------------------


def test_existing_playback_policy_defaults_to_taking_over() -> None:
    assert store.settings["on_existing_playback"] == "TakeOver"

    assert config.existing_playback_policy() is Policy.TAKE_OVER


def test_existing_playback_policy_reads_yield() -> None:
    store.settings["on_existing_playback"] = "Yield"

    assert config.existing_playback_policy() is Policy.YIELD


def test_existing_playback_policy_falls_back_to_taking_over_on_a_stale_value() -> None:
    store.settings["on_existing_playback"] = "SomethingRemoved"

    assert config.existing_playback_policy() is Policy.TAKE_OVER


def test_existing_playback_policy_falls_back_to_taking_over_when_unset() -> None:
    store.settings["on_existing_playback"] = ""

    assert config.existing_playback_policy() is Policy.TAKE_OVER
