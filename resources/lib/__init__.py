"""Module-level singletons shared by every ``resources.lib`` module.

Resolved once at import, per contracts/modules.md.
"""

import xbmcaddon
import xbmcvfs

addon = xbmcaddon.Addon()
addon_id: str = addon.getAddonInfo("id")
addon_name: str = addon.getAddonInfo("name")
addon_version: str = addon.getAddonInfo("version")
profile_dir: str = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
