"""Hand-written fake of the `xbmcvfs` module for pytest (research.md D-008).

Delegates to real filesystem primitives against real (usually ``tmp_path``)
paths rather than simulating a virtual filesystem -- the point of this fake is
only to stand in for a Kodi C-extension name that pytest cannot import, not to
avoid real disk I/O, which pytest's own fixtures already sandbox per test.

``special://`` resolution is a small, test-settable mapping (``SPECIAL_ROOTS``)
rather than a real translator, since no production code needs it to be
byte-for-byte accurate -- only that ``special://skin/`` and
``special://profile/`` resolve to *some* real, writable directory a test
controls.
"""
import os
import shutil
from typing import IO, List, Optional, Tuple

SPECIAL_ROOTS = {
    "profile": "/tmp/fake-kodi-profile/",
    "skin": "/tmp/fake-kodi-skin/",
    "home": "/tmp/fake-kodi-home/",
}


def translatePath(path: str) -> str:
    """Resolve a ``special://<root>/<rest>`` path against ``SPECIAL_ROOTS``."""
    if not path.startswith("special://"):
        return path
    remainder = path[len("special://") :]
    root, _, tail = remainder.partition("/")
    base = SPECIAL_ROOTS.get(root, "/tmp/fake-kodi-%s/" % root)
    return os.path.join(base, tail)


def exists(path: str) -> bool:
    """D-009: the addon MUST use this instead of ``os.path.exists``.

    Reproduces a documented real-Kodi ``xbmcvfs`` quirk: a *directory*'s
    existence only reads True when the path ends with a trailing slash; a
    *file*'s does not need one. Discovered 2026-09 via Tier 2 manual testing
    -- ``os.path.exists`` doesn't care about trailing slashes either way, so
    this fake originally didn't either, and every automated test passed
    while the real skin-hook installer silently failed to recurse into a
    skin's resolution subdirectories (see skinconnector.py's `_find_below`).

    A ``special://`` path is translated first, same as real Kodi resolves it
    to a real location before checking. Any other ``scheme://`` (``http://``
    etc.) has no local file to check and this fake makes no real network
    call, so such a path is simply treated as existing.
    """
    if path.startswith("special://"):
        path = translatePath(path)
    elif "://" in path:
        return True
    if os.path.isdir(path):
        return path.endswith("/")
    return os.path.exists(path)


def mkdir(path: str) -> bool:
    try:
        os.mkdir(path)
        return True
    except OSError:
        return False


def mkdirs(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except OSError:
        return False


def listdir(path: str) -> Tuple[List[str], List[str]]:
    """Matches the real API's ``(directories, files)`` return shape."""
    directories: List[str] = []
    files: List[str] = []
    for entry in os.listdir(path):
        full = os.path.join(path, entry)
        (directories if os.path.isdir(full) else files).append(entry)
    return directories, files


def copy(source: str, destination: str) -> bool:
    try:
        shutil.copyfile(source, destination)
        return True
    except OSError:
        return False


def delete(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def rename(source: str, destination: str) -> bool:
    """Same never-raise convention as ``copy``/``delete``: False on failure.

    ``os.rename`` silently replaces an existing destination on POSIX, which
    is what this fake inherits. Whether real Kodi's ``rename`` does the same
    on every platform is unverified -- callers must not depend on it (see
    ``playlist._replace``).
    """
    try:
        os.rename(source, destination)
        return True
    except OSError:
        return False


class File:
    """Fake of ``xbmcvfs.File``.

    Real Kodi's ``xbmcvfs.File`` does not raise on a *write* permission
    failure -- opening a root-owned skin file for writing silently yields a
    working-looking handle whose ``write()`` returns ``False``, confirmed
    via Tier 2 manual testing (2026-09) against a real non-writable file:
    nothing was written, nothing raised, and the addon's own code -- which
    only checked for an exception -- logged a false "installed" success.
    This fake reproduces that for ``"w"``/``"a"`` modes only: a failed open
    is swallowed here, not left to raise, so callers that only check
    exceptions (rather than ``write()``'s return value) fail the same way in
    tests that they would on real Kodi. Read-mode failures are left to raise
    as before -- there is no equivalent confirmed evidence for ``read()``,
    and changing it without evidence would just be a different guess.
    """

    _WRITE_MODES = ("w", "a")

    def __init__(self, path: str, mode: str = "r") -> None:
        self._handle: Optional[IO[str]] = None
        if mode in self._WRITE_MODES:
            try:
                self._handle = open(path, mode)
            except OSError:
                pass
        else:
            self._handle = open(path, mode)

    def read(self, num_bytes: int = 0) -> str:
        if self._handle is None:
            return ""
        return self._handle.read(num_bytes or -1)

    def write(self, data: str) -> bool:
        if self._handle is None:
            return False
        try:
            self._handle.write(data)
            return True
        except OSError:
            return False

    def size(self) -> int:
        if self._handle is None:
            return 0
        position = self._handle.tell()
        self._handle.seek(0, os.SEEK_END)
        end = self._handle.tell()
        self._handle.seek(position)
        return end

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()


class Stat:
    """Fake of ``xbmcvfs.Stat`` -- methods, not properties, matching the
    real API's ``st_mtime()``/``st_size()`` call shape."""

    def __init__(self, path: str) -> None:
        self._stat = os.stat(path)

    def st_mtime(self) -> float:
        return self._stat.st_mtime

    def st_size(self) -> int:
        return self._stat.st_size
