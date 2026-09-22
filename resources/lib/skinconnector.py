"""Maintain the addon's ``<onload>`` hook in the skin's SlideShow.xml (D-007).

A Script Mode addon cannot launch itself, so this injected element is the only
mechanism that tells Kodi to run the addon when the slideshow window opens
(contracts/skin-integration.md). The hook is identified by its ``RunAddon``
text alone: a user may have edited the condition deliberately, and that is
still "present".

Every filesystem operation goes through ``xbmcvfs`` rather than ``os``, because
a skin directory can carry non-ASCII path segments that break under Kodi's
ASCII ``filesystemencoding`` (D-009); ``os.path`` is used only for string-level
path joining and splitting, which touches no filesystem. Readability and
writability have no ``xbmcvfs`` predicate, so they are probed by opening the
file and by creating and deleting a probe file in its directory -- neither
touches the skin file's own content, which the contract forbids before a
successful precondition run.

Parsing keeps XML comments (``insert_comments``) so a skin author's own file is
handed back with everything but the hook unchanged.
"""

import enum
import os
import re
import xml.etree.ElementTree as ElementTree
from typing import List, NamedTuple, Optional, Tuple

import xbmc
import xbmcvfs

from resources import lib
from resources.lib import messages

SLIDESHOW_FILENAME = "slideshow.xml"
BACKUP_SUFFIX = ".original"
WINDOW_TAG = "window"
ONLOAD_TAG = "onload"
DEFAULT_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'

_DECLARATION_RE = re.compile(r"^<\?xml[^>]*\?>")

HOOK_TEXT = "RunAddon({0})".format(lib.addon_id)
HOOK_CONDITION = "System.HasAddon({0}) + System.AddonIsEnabled({0})".format(
    lib.addon_id
)

_PROBE_FILENAME = ".slideshow-bgm-write-probe"

_REASON_NOT_FOUND = "no SlideShow.xml found under special://skin for skin {skin}"
_REMEDY_NOT_FOUND = (
    "this skin may not support slideshow integration; try a different skin"
)
_REASON_NOT_READABLE = "SlideShow.xml exists but is not readable: {path}"
_REMEDY_NOT_READABLE = "check file permissions for the user running Kodi"
_REASON_NOT_WRITABLE = "SlideShow.xml or its directory is not writable: {path}"
_REMEDY_NOT_WRITABLE = (
    "grant write permission, e.g. chmod u+w {path} or edit {path} using sudo, "
    "then restart Kodi"
)
_REASON_UNPARSEABLE = "SlideShow.xml is not valid XML or has no root <window>: {path}"
_REMEDY_UNPARSEABLE = "the skin file may be corrupted; try reinstalling the skin"


def find_slideshow_xml() -> List[str]:
    """Find every ``SlideShow.xml`` the active skin ships.

    A skin can carry one copy per resolution directory (``1080i/``, ``16x9/``,
    ...) and Kodi picks between them at runtime, so all of them are returned
    and all of them must be hooked.

    Returns:
        Absolute paths, sorted; empty when the skin ships none.
    """
    return sorted(_find_below(xbmcvfs.translatePath("special://skin/")))


def _with_trailing_slash(directory: str) -> str:
    """Normalize a directory path the way ``xbmcvfs`` requires it.

    Real Kodi's ``xbmcvfs.exists``/``listdir`` only recognize a *directory*
    when its path ends with ``/`` -- a file's doesn't need one, but a bare
    ``os.path.join(parent, subdir_name)`` never adds one, so every
    subdirectory found while recursing silently failed this check and
    ``_find_below`` stopped one level too early. Confirmed against Kodi's own
    forum (documented VFS behavior) after Tier 2 manual testing caught a
    skin's ``<resolution>/SlideShow.xml`` never being found.

    Args:
        directory: A directory path, with or without a trailing slash.

    Returns:
        The same path, guaranteed to end with ``/``.
    """
    return directory if directory.endswith("/") else directory + "/"


def _find_below(directory: str) -> List[str]:
    """Recursively collect SlideShow.xml paths under a directory.

    Args:
        directory: Directory to search.

    Returns:
        Absolute paths of every case-insensitive ``SlideShow.xml`` match.
    """
    directory = _with_trailing_slash(directory)
    if not xbmcvfs.exists(directory):
        return []
    subdirectories, filenames = xbmcvfs.listdir(directory)
    found = [
        os.path.join(directory, name)
        for name in filenames
        if name.lower() == SLIDESHOW_FILENAME
    ]
    for name in subdirectories:
        found.extend(_find_below(_with_trailing_slash(os.path.join(directory, name))))
    return found


def is_hooked(path: str) -> bool:
    """Whether the addon's ``<onload>`` is already in this file.

    Args:
        path: SlideShow.xml to inspect.

    Returns:
        True when an ``<onload>`` carrying the addon's ``RunAddon`` text exists
        under the root ``<window>``, whatever its condition says.
    """
    root = _parse(path)
    return root is not None and _find_hook(root) is not None


class SlideshowFileState(enum.Enum):
    """What one of the skin's slideshow files needs (specs/002 data-model.md)."""

    INTEGRATED = "integrated"
    NEEDS_INTEGRATION = "needs_integration"
    NOT_MODIFIABLE = "not_modifiable"


class _Inspected(NamedTuple):
    """A slideshow file that passed every precondition, read exactly once."""

    content: str
    root: ElementTree.Element


def _inspect(path: str) -> Optional[_Inspected]:
    """Run the preconditions and parse the file, without modifying it.

    The one inspection :func:`assess` and :func:`install` share, so the
    question the user is asked and the install that follows it cannot
    disagree about what a file is (specs/002 D-017). Checks run in the order
    fixed by contracts/skin-integration.md -- found, readable, writable,
    parseable -- and the first failure stops and is logged with its reason and
    remedy (FR-015).

    Args:
        path: SlideShow.xml to inspect.

    Returns:
        The file's content and parsed root, or None when it cannot be
        modified.
    """
    if not _preconditions_ok(path):
        return None
    content = _read(path)
    if content is None:
        _log_failure(path, _REASON_NOT_READABLE, _REMEDY_NOT_READABLE)
        return None
    root = _parse_content(content)
    if root is None:
        _log_failure(path, _REASON_UNPARSEABLE, _REMEDY_UNPARSEABLE)
        return None
    return _Inspected(content, root)


def _hook_present(root: ElementTree.Element, path: str) -> bool:
    """Whether the hook is already in the file, logging it when it is.

    Args:
        root: Parsed root ``<window>`` element.
        path: The file ``root`` came from, for the log line.

    Returns:
        True when the addon's ``<onload>`` is present, whatever its condition.
    """
    if _find_hook(root) is None:
        return False
    messages.log("skin hook: already present ({0})".format(path), xbmc.LOGDEBUG)
    return True


def assess(path: str) -> SlideshowFileState:
    """Classify a slideshow file without modifying it.

    Lets the caller ask the user before :func:`install` writes anything
    (specs/002 FR-001). Failures are logged exactly as :func:`install` logs
    them, because both go through :func:`_inspect`. The writability probe is
    the same empty append and transient probe file :func:`install` already
    performs; the skin file's content is never changed (research.md R-11).

    Args:
        path: SlideShow.xml to assess.

    Returns:
        ``NOT_MODIFIABLE`` when a precondition failed, ``INTEGRATED`` when the
        addon's hook is already present, otherwise ``NEEDS_INTEGRATION``.
    """
    inspected = _inspect(path)
    if inspected is None:
        return SlideshowFileState.NOT_MODIFIABLE
    if _hook_present(inspected.root, path):
        return SlideshowFileState.INTEGRATED
    return SlideshowFileState.NEEDS_INTEGRATION


def install(path: str) -> bool:
    """Inject the addon's ``<onload>`` as the last child of ``<window>``.

    Preconditions are checked in the order fixed by
    contracts/skin-integration.md -- found, readable, writable, parseable --
    and the first failure aborts without writing anything, logging its reason
    and a remedy (FR-015). Already-hooked files are left exactly as they are,
    so repeated calls never accumulate duplicates. Whether the user has agreed
    to the change is the caller's business (specs/002); this always re-inspects
    the file, so a change made since :func:`assess` is caught here.

    Args:
        path: SlideShow.xml to hook.

    Returns:
        True when the file is hooked, including when it already was.
    """
    inspected = _inspect(path)
    if inspected is None:
        return False
    root = inspected.root
    if _hook_present(root, path):
        return True
    declaration, trailing_newline = _declaration_and_trailing_newline(inspected.content)
    if not _back_up(path):
        _log_failure(path, _REASON_NOT_WRITABLE, _REMEDY_NOT_WRITABLE)
        return False
    _append_hook(root)
    if not _write(path, root, declaration, trailing_newline):
        _roll_back(path)
        _log_failure(path, _REASON_NOT_WRITABLE, _REMEDY_NOT_WRITABLE)
        return False
    messages.log("skin hook: installed ({0})".format(path), xbmc.LOGINFO)
    return True


def uninstall(path: str) -> bool:
    """Remove the addon's own ``<onload>``, leaving every other element alone.

    Args:
        path: SlideShow.xml to clean.

    Returns:
        True when the file holds no addon hook afterwards -- including when it
        never did. False when the file could not be parsed or rewritten.
    """
    content = _read(path)
    if content is None:
        return False
    root = _parse_content(content)
    if root is None:
        return False
    hook = _find_hook(root)
    if hook is None:
        return True
    for parent in root.iter():
        if hook in list(parent):
            parent.remove(hook)
    declaration, trailing_newline = _declaration_and_trailing_newline(content)
    if _write(path, root, declaration, trailing_newline):
        return True
    _roll_back(path)
    return False


def _roll_back(path: str) -> None:
    """Put a skin file back from its ``.original`` after a failed write.

    :func:`_write` opens with mode ``"w"``, which empties the live skin file
    before a single byte is written, so a write that dies partway leaves the
    skin's own SlideShow.xml truncated -- a third-party file this addon has
    no other way to reconstruct. ``install`` always takes a backup first
    (:func:`_back_up`), which exists precisely so this recovery is possible;
    ``uninstall`` reuses whatever backup an earlier install left, since the
    pristine pre-hook file is exactly what it was trying to arrive at anyway.

    ``xbmcvfs.copy`` can fail without raising (D-009), so its return value
    decides which of the two outcomes is logged. A failed rollback is the
    genuinely damaging case and names the backup so the user can restore it
    by hand.

    Args:
        path: The skin file whose write just failed.
    """
    backup = path + BACKUP_SUFFIX
    if not xbmcvfs.exists(backup):
        messages.log(
            "skin hook: writing {0} failed and no backup exists at {1}; the file "
            "may be left truncated".format(path, backup),
            xbmc.LOGERROR,
        )
        return
    if xbmcvfs.copy(backup, path):
        messages.log(
            "skin hook: writing {0} failed; restored it from {1}".format(path, backup),
            xbmc.LOGERROR,
        )
        return
    messages.log(
        "skin hook: writing {0} failed AND restoring it from {1} failed too; the "
        "file may be left truncated -- restore it by hand from {1}".format(
            path, backup
        ),
        xbmc.LOGERROR,
    )


def _preconditions_ok(path: str) -> bool:
    """Check the found/readable/writable preconditions, in that order.

    Args:
        path: SlideShow.xml to check.

    Returns:
        True when every check passed; otherwise False, with the first failure
        logged.
    """
    if not xbmcvfs.exists(path):
        _log_failure(path, _REASON_NOT_FOUND.format(skin=_skin_id()), _REMEDY_NOT_FOUND)
        return False
    if not _is_readable(path):
        _log_failure(path, _REASON_NOT_READABLE, _REMEDY_NOT_READABLE)
        return False
    if not _is_writable(path):
        _log_failure(path, _REASON_NOT_WRITABLE, _REMEDY_NOT_WRITABLE)
        return False
    return True


def _log_failure(path: str, reason: str, remedy: str) -> None:
    """Log one install failure in the shape fixed by contracts/logging.md.

    Args:
        path: File the install was attempted on.
        reason: Reason template; ``{path}`` is filled in.
        remedy: Remedy template; ``{path}`` is filled in.
    """
    messages.log(
        "skin hook: install failed at {0} — {1}. Fix: {2}".format(
            path, reason.format(path=path), remedy.format(path=path)
        ),
        xbmc.LOGERROR,
    )


def _skin_id() -> str:
    """Name the active skin for the not-found message.

    Kodi's skin id is the last segment of the directory ``special://skin/``
    resolves to, which keeps this on ``xbmcvfs`` rather than a second API.

    Returns:
        The skin directory's name, e.g. ``skin.estuary``.
    """
    skin_root: str = xbmcvfs.translatePath("special://skin/")
    return os.path.basename(os.path.normpath(skin_root))


def _is_readable(path: str) -> bool:
    """Whether the file can actually be opened for reading.

    Args:
        path: File to probe.

    Returns:
        True when opening and reading it succeeds.
    """
    return _read(path) is not None


def _is_writable(path: str) -> bool:
    """Whether both the file and its directory accept writes.

    The directory matters because the ``.original`` backup is created there.
    The probe writes a throwaway file rather than the skin file itself, so a
    failed precondition leaves the skin file untouched.

    Real Kodi's ``xbmcvfs.File`` does not raise on a permission failure --
    ``write()`` returns ``False`` instead, confirmed via Tier 2 manual
    testing against a real root-owned file, where opening and closing a
    handle *without ever writing* reported success even though the file was
    never actually writable. Every probe here therefore performs a real
    (harmless, empty) write and checks its return value -- open-then-close
    alone cannot observe this failure mode at all.

    Args:
        path: File to probe.

    Returns:
        True when the file is appendable and its directory accepts a new file.
    """
    handle = xbmcvfs.File(path, "a")
    file_writable = handle.write("")
    handle.close()
    if not file_writable:
        return False
    probe = os.path.join(os.path.dirname(path), _PROBE_FILENAME)
    probe_handle = xbmcvfs.File(probe, "w")
    directory_writable = probe_handle.write("")
    probe_handle.close()
    xbmcvfs.delete(probe)
    return bool(directory_writable)


def _read(path: str) -> Optional[str]:
    """Read a file's whole contents through ``xbmcvfs``.

    Args:
        path: File to read.

    Returns:
        The contents, or None when the file cannot be read.
    """
    try:
        handle = xbmcvfs.File(path, "r")
        try:
            content: str = handle.read()
            return content
        finally:
            handle.close()
    except (OSError, IOError, UnicodeDecodeError):
        return None


def _parse(path: str) -> Optional[ElementTree.Element]:
    """Parse a SlideShow.xml, keeping the skin author's comments.

    Args:
        path: File to parse.

    Returns:
        The root element when it is a ``<window>``; None when the file is
        unreadable, malformed, or rooted at something else.
    """
    content = _read(path)
    if content is None:
        return None
    return _parse_content(content)


def _parse_content(content: str) -> Optional[ElementTree.Element]:
    """Parse already-read SlideShow.xml content, keeping the author's comments.

    Split out from :func:`_parse` so ``install``/``uninstall`` can read a
    file's content exactly once and derive both the element tree and its
    original formatting (:func:`_declaration_and_trailing_newline`) from the
    same read, rather than reading it twice and risking the two disagreeing.

    Args:
        content: A SlideShow.xml file's full text.

    Returns:
        The root element when it is a ``<window>``; None when the content is
        malformed or rooted at something else.
    """
    parser = ElementTree.XMLParser(target=ElementTree.TreeBuilder(insert_comments=True))
    try:
        root = ElementTree.fromstring(content, parser=parser)
    except ElementTree.ParseError:
        return None
    return root if root.tag == WINDOW_TAG else None


def _declaration_and_trailing_newline(content: str) -> Tuple[str, bool]:
    """Capture formatting :func:`_write` must reproduce, not just re-derive.

    Rewriting a parsed ``ElementTree`` loses the file's original XML
    declaration entirely (it isn't part of the tree) and any trailing
    newline. A hardcoded declaration and an always-added-or-dropped newline
    each silently changed bytes the skin author wrote that had nothing to do
    with the hook -- found via Tier 2 manual testing against a real skin file
    using single-quote, lowercase-``utf-8`` style.

    Args:
        content: The file's original content, before any edit.

    Returns:
        The original declaration verbatim (or a default when none was
        present), and whether the original content ended with a newline.
    """
    match = _DECLARATION_RE.match(content)
    declaration = match.group(0) if match else DEFAULT_XML_DECLARATION
    return declaration, content.endswith("\n")


def _find_hook(root: ElementTree.Element) -> Optional[ElementTree.Element]:
    """Locate the addon's own ``<onload>`` element.

    Args:
        root: Parsed root ``<window>`` element.

    Returns:
        The matching element, or None when the file is not hooked.
    """
    for element in root.iter(ONLOAD_TAG):
        if (element.text or "").strip() == HOOK_TEXT:
            return element
    return None


def _append_hook(root: ElementTree.Element) -> None:
    """Add the hook as the last child of the root ``<window>``.

    Args:
        root: Parsed root ``<window>`` element, modified in place.
    """
    element = ElementTree.SubElement(root, ONLOAD_TAG, {"condition": HOOK_CONDITION})
    element.text = HOOK_TEXT
    element.tail = "\n"


def _back_up(path: str) -> bool:
    """Copy the file to ``<path>.original`` before its first edit.

    An existing backup is never overwritten: it must stay a copy of the skin's
    pristine file, not of a previously hooked one. ``xbmcvfs.copy`` can fail
    without raising (the same non-raising-on-failure convention ``write()``
    has), so its return value is checked -- silently continuing past a
    failed backup would mean editing a file with no pristine copy preserved,
    breaking FR-015's promise before the hook is even applied.

    Args:
        path: File to back up.

    Returns:
        True when a backup exists afterward, whether it already did or was
        just created; False when creating it failed.
    """
    backup = path + BACKUP_SUFFIX
    if xbmcvfs.exists(backup):
        return True
    return bool(xbmcvfs.copy(path, backup))


def _write(
    path: str, root: ElementTree.Element, declaration: str, trailing_newline: bool
) -> bool:
    """Serialize a parsed tree back over the file it came from.

    Args:
        path: File to overwrite.
        root: Root element to write.
        declaration: XML declaration line to write verbatim (no trailing
            newline of its own -- one is always inserted after it).
        trailing_newline: Whether to end the file with a newline, matching
            whatever the original file did.

    Returns:
        True when the file was actually written. Real Kodi's ``xbmcvfs``
        does not always raise on a write failure -- ``write()`` can return
        ``False`` instead (confirmed via Tier 2 manual testing) -- so that
        return value is checked here rather than assumed from the absence
        of an exception; the ``try``/``except`` stays as a second line of
        defense for whichever failure mode a given VFS backend does raise.
    """
    body = ElementTree.tostring(root, encoding="unicode")
    content = declaration + "\n" + body + ("\n" if trailing_newline else "")
    try:
        handle = xbmcvfs.File(path, "w")
        try:
            written = handle.write(content)
        finally:
            handle.close()
    except (OSError, IOError):
        return False
    return bool(written)
