"""Read and validate the addon's settings (FR-005..FR-008, FR-012, FR-014).

Nothing here talks to the user: ``read_source`` and ``validate`` are pure with
respect to the UI, which is what makes validation testable without a display
(contracts/modules.md). Deciding what a failed :func:`validate` should *say*
belongs to ``session.py``, the only caller, because the surface depends on
when it happens -- and in Script Mode that is only ever at slideshow start
(D-010's 2026-09-15 addendum).

``resources.lib`` is imported as a module so the ``addon`` singleton is read at
call time rather than bound at import.
"""

import enum
from typing import NamedTuple, Optional

import xbmcvfs

from resources import lib
from resources.lib import playlist
from resources.lib.playlist import DIRECTORY, PLAYLIST, BgmSource, PlaylistFormat

NOT_SELECTED = "Not Selected"

SETTING_TYPE = "type"
SETTING_PLAYLIST = "playlist"
SETTING_DIRECTORY = "directory"
SETTING_RANDOM = "random"
SETTING_ON_EXISTING_PLAYBACK = "on_existing_playback"


class Reason(enum.Enum):
    """Why a source failed validation (contracts/settings.md).

    Attributes:
        NOT_SELECTED: The path setting still holds the unconfigured sentinel.
        MISSING: The configured path does not exist.
        NOT_MUSIC_PLAYLIST: A .xsp smart playlist whose root type is not
            songs (or the legacy music alias).
        EMPTY: The source resolved to no playable entry.
    """

    NOT_SELECTED = "not_selected"
    MISSING = "missing"
    NOT_MUSIC_PLAYLIST = "not_music_playlist"
    EMPTY = "empty"


class Policy(enum.Enum):
    """What to do when Kodi is already playing audio at slideshow start (FR-014).

    Attributes:
        TAKE_OVER: Stop existing playback and start BGM. The default.
        YIELD: Leave existing playback alone and skip BGM this slideshow.
    """

    TAKE_OVER = "TakeOver"
    YIELD = "Yield"


class ValidationResult(NamedTuple):
    """Outcome of validating a source.

    Attributes:
        ok: True when the source is usable.
        reason: Which check failed; None when ``ok`` is True.
    """

    ok: bool
    reason: Optional[Reason] = None


def read_source() -> Optional[BgmSource]:
    """Build a :class:`BgmSource` from the current settings.

    The ``type`` setting decides which path setting is live, so only that one
    is read. The unconfigured sentinel (and an empty value) counts as "no
    source configured" rather than as a path, per contracts/settings.md.

    This is where FR-008 is enforced: the ``random`` setting is a *request*,
    and a source whose format carries its own order overrules it. Doing it
    here rather than in ``player.py`` means every consumer -- the player, the
    ``session start`` log line -- sees one already-reconciled answer.

    Returns:
        The configured source, or None when no source has been chosen.
    """
    kind = DIRECTORY if lib.addon.getSetting(SETTING_TYPE) == "Directory" else PLAYLIST
    setting_id = SETTING_DIRECTORY if kind == DIRECTORY else SETTING_PLAYLIST
    path = lib.addon.getSetting(setting_id)
    if not path or path == NOT_SELECTED:
        return None
    requested = lib.addon.getSettingBool(SETTING_RANDOM)
    source = BgmSource(kind=kind, path=path, shuffle=requested)
    if requested and not source.supports_shuffle:
        # FR-008: a .pls/.xsp playlist plays in its own native order. D-011's
        # settings-UI grey-out only advertises this; it is not what enforces
        # it, and its `contains` heuristic can disagree with the real
        # extension in both directions.
        return source._replace(shuffle=False)
    return source


def validate(source: BgmSource) -> ValidationResult:
    """Run the four ordered checks from contracts/settings.md.

    The order matters: an unconfigured sentinel is never handed to the
    filesystem, and a missing path is never handed to the resolver.

    Args:
        source: The source to check.

    Returns:
        A passing result, or a failing one naming the first check that failed.
    """
    if not source.path or source.path == NOT_SELECTED:
        return ValidationResult(False, Reason.NOT_SELECTED)
    if not xbmcvfs.exists(_existence_check_path(source)):
        return ValidationResult(False, Reason.MISSING)
    if (
        source.playlist_format is PlaylistFormat.XSP
        and not playlist.is_music_smartplaylist(source.path)
    ):
        return ValidationResult(False, Reason.NOT_MUSIC_PLAYLIST)
    if playlist.resolve(source) is None:
        return ValidationResult(False, Reason.EMPTY)
    return ValidationResult(True, None)


def _existence_check_path(source: BgmSource) -> str:
    """The path to hand ``xbmcvfs.exists``, normalized for its directory quirk.

    Real Kodi's ``xbmcvfs.exists`` only recognizes a *directory* as existing
    when its path ends with a trailing slash; a *file*'s must not have one
    added (documented Kodi VFS behavior, found via Tier 2 manual testing --
    see skinconnector.py's identical fix). A ``DIRECTORY`` source's path, as
    read from settings, carries no guarantee either way, so it is normalized
    here; a ``PLAYLIST`` source's path is a file and passes through as-is.

    Args:
        source: The source about to be existence-checked.

    Returns:
        ``source.path``, with a trailing slash added for a directory source
        that doesn't already have one.
    """
    if source.kind is DIRECTORY and not source.path.endswith("/"):
        return source.path + "/"
    return source.path


def existing_playback_policy() -> Policy:
    """Read what to do when audio is already playing (FR-014).

    Returns:
        :attr:`Policy.YIELD` when the user chose it; :attr:`Policy.TAKE_OVER`
        otherwise, including for an unset or stale setting value.
    """
    if lib.addon.getSetting(SETTING_ON_EXISTING_PLAYBACK) == Policy.YIELD.value:
        return Policy.YIELD
    return Policy.TAKE_OVER
