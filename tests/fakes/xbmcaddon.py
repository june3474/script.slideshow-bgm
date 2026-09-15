"""Hand-written fake of the `xbmcaddon` module for pytest (research.md D-008).

Backs every setting with a single string store, matching how Kodi actually
persists ``settings.xml`` values, and layers the typed ``getSettingBool``/
``getSettingInt``/``getSettingString`` accessors on top by converting on
access -- exactly what the real ``xbmcaddon.Addon`` does.
"""
from typing import Dict, Optional

DEFAULT_SETTINGS: Dict[str, str] = {
    "type": "Playlist",
    "playlist": "Not Selected",
    "directory": "Not Selected",
    "random": "true",
    "on_existing_playback": "TakeOver",
}

DEFAULT_ADDON_INFO: Dict[str, str] = {
    "id": "script.slideshow-bgm",
    "name": "Slideshow-BGM",
    "version": "0.1.0",
    "profile": "special://profile/addon_data/script.slideshow-bgm/",
    "path": "special://home/addons/script.slideshow-bgm/",
}


class _AddonStore:
    """Module-level state so every ``Addon()`` instance in a test sees the
    same settings, reset per test by ``tests/conftest.py``."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.settings: Dict[str, str] = dict(DEFAULT_SETTINGS)
        self.addon_info: Dict[str, str] = dict(DEFAULT_ADDON_INFO)
        self.localized_strings: Dict[int, str] = {}


store = _AddonStore()


class Addon:
    """Fake of ``xbmcaddon.Addon``. The ``id`` argument is accepted for
    signature compatibility and ignored -- the fake models exactly one
    addon's settings, which is all this project ever instantiates."""

    def __init__(self, id: Optional[str] = None) -> None:
        del id

    def getSetting(self, id: str) -> str:
        return store.settings.get(id, "")

    def setSetting(self, id: str, value: str) -> None:
        store.settings[id] = value

    def getSettingBool(self, id: str) -> bool:
        return store.settings.get(id, "false").lower() == "true"

    def setSettingBool(self, id: str, value: bool) -> None:
        store.settings[id] = "true" if value else "false"

    def getSettingInt(self, id: str) -> int:
        return int(store.settings.get(id, "0") or "0")

    def setSettingInt(self, id: str, value: int) -> None:
        store.settings[id] = str(value)

    def getSettingString(self, id: str) -> str:
        return self.getSetting(id)

    def setSettingString(self, id: str, value: str) -> None:
        self.setSetting(id, value)

    def getAddonInfo(self, key: str) -> str:
        return store.addon_info.get(key, "")

    def getLocalizedString(self, id: int) -> str:
        return store.localized_strings.get(id, str(id))
