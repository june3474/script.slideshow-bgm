"""Resolve a BGM source into a playlist file for PlayMedia (FR-006, FR-010, D-009).

Directory sources are scanned recursively and flattened into ``bgm.m3u`` in the
addon profile directory; a plain ``.m3u`` playlist source is handed through as
it is. ``.pls``/``.xsp`` sources are resolved into a track list of their own
(via :func:`parse_pls`/:func:`resolve_xsp`) and flattened into that same
``bgm.m3u`` too -- real-device testing found Kodi's own ``playoffset`` resume
never advances past track 1 for these two formats, so this addon can no longer
just hand Kodi the raw file and trust its own playlist-player internals. The
scan walks **bytes** paths and only ever decodes for output, because Kodi runs
with an ASCII ``filesystemencoding`` where a ``str`` walk raises ``UnicodeError``
on a non-ASCII filename (D-009). Every existence or size check goes through
``xbmcvfs`` for the same reason.

``bgm.m3u`` is derived afresh on every resolve and never cached across
slideshow starts -- see :func:`_resolve_derived` for why D-009's mtime cache
was retired on 2026-09-15. It is only rewritten when the newly derived track
list differs from the one it already holds, so the common, unchanged case
touches the filesystem not at all.

``resources.lib`` is imported as a module (rather than ``from ... import
profile_dir``) so the profile location is read at call time -- the addon reads
it once at startup, and tests point it at a temporary directory.
"""

import enum
import json
import os
import time
import xml.etree.ElementTree as ElementTree
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

import xbmc
import xbmcvfs

from resources import lib
from resources.lib import messages


class SourceKind(enum.Enum):
    """Which shape a :class:`BgmSource` is (data-model.md).

    Attributes:
        PLAYLIST: A user-chosen ``.m3u``/``.pls``/``.xsp`` file.
        DIRECTORY: A directory recursively scanned into a derived playlist.
    """

    PLAYLIST = "PLAYLIST"
    DIRECTORY = "DIRECTORY"


class PlaylistFormat(enum.Enum):
    """Which playlist format a :class:`BgmSource` plays (data-model.md).

    Attributes:
        M3U: A bare path-per-line playlist, including the ``bgm.m3u`` a
            directory source derives. Honors shuffle.
        PLS: An INI-style playlist. Plays in its own native order (FR-008).
        XSP: A Kodi smart playlist. Plays in its own native order (FR-008).
    """

    M3U = "M3U"
    PLS = "PLS"
    XSP = "XSP"


PLAYLIST = SourceKind.PLAYLIST
DIRECTORY = SourceKind.DIRECTORY

#: Extensions whose playlists carry an order of their own that shuffle must
#: not override (FR-008). Matched lowercased, so a ``.PLS`` file behaves like
#: a ``.pls`` one -- D-011's settings-UI grey-out may be case-sensitive, but
#: the runtime behavior it only advertises must not be.
_UNSHUFFLEABLE_EXTENSIONS = {".pls": PlaylistFormat.PLS, ".xsp": PlaylistFormat.XSP}

AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".wma", ".flac", ".aac", ".m4a")
M3U_FILENAME = "bgm.m3u"

#: Appended to a derived playlist's own path to name the temporary file
#: :func:`write_m3u` builds the new generation in. A sibling, not a system
#: temp file, so the replacing move never crosses a filesystem.
PARTIAL_SUFFIX = ".part"

_ENCODED_EXTENSIONS = tuple(extension.encode("ascii") for extension in AUDIO_EXTENSIONS)


class BgmSource(NamedTuple):
    """Where background music comes from.

    The minimal shape this module needs; ``config.py`` owns the full model
    described in data-model.md and is what builds one from settings.

    Attributes:
        kind: :data:`PLAYLIST` or :data:`DIRECTORY`.
        path: The playlist file or music directory the user chose.
        shuffle: Whether playback is shuffled (setting ``random``, FR-008).
    """

    kind: SourceKind
    path: str
    shuffle: bool = True

    @property
    def playlist_format(self) -> PlaylistFormat:
        """Which :class:`PlaylistFormat` this source ends up playing.

        A directory source is always :attr:`PlaylistFormat.M3U`: what reaches
        ``PlayMedia`` is the ``bgm.m3u`` this module derives, whatever the
        directory itself happens to be called. Anything FR-007's settings
        ``<masking>`` did not catch falls back to ``M3U`` too, because FR-008
        only ever carves out ``.pls`` and ``.xsp``.

        Returns:
            The format of the playlist actually handed to Kodi.
        """
        if self.kind == DIRECTORY:
            return PlaylistFormat.M3U
        extension = os.path.splitext(self.path)[1].lower()
        return _UNSHUFFLEABLE_EXTENSIONS.get(extension, PlaylistFormat.M3U)

    @property
    def supports_shuffle(self) -> bool:
        """Whether shuffle can be honored for this source (FR-008).

        Returns:
            False for a ``.pls`` or ``.xsp`` playlist, which plays in its own
            native order regardless of the ``random`` setting; True otherwise.
        """
        return self.playlist_format is PlaylistFormat.M3U


def scan_directory(path: str) -> List[str]:
    """Recursively collect supported audio files under a directory (FR-006).

    Args:
        path: Directory to walk. A missing directory yields no tracks.

    Returns:
        Absolute paths of every matching file, sorted for stable playlists.
    """
    tracks: List[str] = []
    for root, _directories, filenames in os.walk(path.encode("utf-8")):
        for filename in filenames:
            if filename.lower().endswith(_ENCODED_EXTENSIONS):
                full = os.path.join(root, filename)
                tracks.append(full.decode("utf-8", "surrogateescape"))
    return sorted(tracks)


def parse_pls(path: str) -> List[str]:
    """Resolve a ``.pls`` playlist into an ordered list of track paths (FR-008).

    Mirrors the philosophy of Kodi's own ``CPlayListPLS::Load()``:
    ``NumberOfEntries`` is only a hint, never trusted for correctness. Every
    line is scanned for a ``File<N>=`` entry (case-insensitive key) and the
    list is built from whatever was actually found, sorted by ``N`` -- this
    tolerates gaps or out-of-order indices without needing to replicate the
    C++ original's stricter behavior. This is a reader for the addon's own
    resolve step, not a general-purpose PLS writer/validator.

    Once resolved, each entry is also checked with ``xbmcvfs.exists`` --
    never ``os.path.exists`` (D-009: Kodi's ASCII ``filesystemencoding`` can
    misbehave when a non-ASCII path is handed straight to the OS) -- and
    dropped if the file it points to does not exist, so a stale reference
    never ends up in the derived ``bgm.m3u``. This is a second, independent
    pass over the already-parsed entries: the ``NumberOfEntries`` check above
    only compares against however many ``File<N>=`` lines were actually
    found, never against whether those files exist.

    Args:
        path: The ``.pls`` file to parse.

    Returns:
        Track paths in ascending ``File<N>=`` order, with a relative entry
        resolved against ``path``'s own directory and any entry whose
        resolved file does not exist dropped. Empty when the file is
        unreadable, does not start with a ``[playlist]`` header, or every
        entry turned out missing.
    """
    content = _read_text(path)
    if content is None or not _has_playlist_header(content):
        messages.log(
            "unreadable or malformed .pls file: {0}".format(path), xbmc.LOGERROR
        )
        return []
    entries: Dict[int, str] = {}
    declared_count: Optional[int] = None
    for line in content.splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "numberofentries":
            try:
                declared_count = int(value)
            except ValueError:
                pass
            continue
        if key.startswith("file") and key[len("file") :].isdigit() and value:
            entries[int(key[len("file") :])] = _resolve_pls_path(value, path)
    if declared_count is not None and declared_count != len(entries):
        messages.log(
            "NumberOfEntries={0} does not match {1} actual File<N>= entries "
            "in {2}".format(declared_count, len(entries), path),
            xbmc.LOGWARNING,
        )
    ordered = [entries[index] for index in sorted(entries)]
    existing = [track for track in ordered if xbmcvfs.exists(track)]
    missing = len(ordered) - len(existing)
    if missing:
        messages.log(
            "{0} of {1} File<N>= entries in {2} reference a file that does "
            "not exist and were skipped".format(missing, len(ordered), path),
            xbmc.LOGWARNING,
        )
    return existing


def _has_playlist_header(content: str) -> bool:
    """Whether a ``.pls``'s first non-blank line is ``[playlist]``.

    Args:
        content: The file's whole text content.

    Returns:
        True when the first non-blank line is ``[playlist]``, case-insensitive.
    """
    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped.lower() == "[playlist]"
    return False


def _resolve_pls_path(value: str, pls_path: str) -> str:
    """Resolve one ``File<N>=`` value against its ``.pls``'s own directory.

    Args:
        value: The raw, already-stripped value.
        pls_path: The ``.pls`` file this value came from.

    Returns:
        ``value`` unchanged when already absolute or a URL/``special://``
        path; otherwise joined onto ``pls_path``'s directory.
    """
    if os.path.isabs(value) or "://" in value:
        return value
    return os.path.join(os.path.dirname(pls_path), value)


def _read_text(path: str) -> Optional[str]:
    """Read a file's whole text content through ``xbmcvfs`` (D-009).

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


_XSP_PAGE_SIZE = 1000

#: Kodi's own default save location for music smart playlists -- see
#: :func:`_prefer_special_musicplaylists` for why this is the profile-relative
#: form rather than the more obvious ``special://musicplaylists/`` alias.
_MUSIC_PLAYLISTS_ROOT = "special://profile/playlists/music/"


def resolve_xsp(path: str) -> List[str]:
    """Resolve a Kodi smart playlist (``.xsp``) into real track paths (FR-008).

    Calls the same ``Files.GetDirectory`` JSON-RPC method Kodi's own
    smart-playlist "Browse into" UI uses to list a ``.xsp``'s matching tracks
    (``CSmartPlaylistDirectory`` -> ``CMusicDatabase::GetItems()``), paginated
    the same way. Runs in-process via ``xbmc.executeJSONRPC``; never raises,
    so a bad source only disables BGM for the session (D-010/FR-010).

    Args:
        path: The ``.xsp`` file's own path.

    Returns:
        Ordered real audio file paths, or an empty list on any JSON-RPC error
        or malformed response.
    """
    path = _prefer_special_musicplaylists(path)
    paths: List[str] = []
    start = 0
    while True:
        response = xbmc.executeJSONRPC(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "Files.GetDirectory",
                    "params": {
                        "directory": path,
                        "media": "music",
                        # "filetype" is always in the response already (Kodi's
                        # own List.Item.File schema marks it required) -- it is
                        # not a valid value to *request* via "properties"
                        # (List.Fields.Files' enum does not include it).
                        # Asking for it makes Kodi reject the whole call with
                        # a schema-validation error (real-device T041 finding).
                        "properties": ["file"],
                        "limits": {"start": start, "end": start + _XSP_PAGE_SIZE},
                    },
                }
            )
        )
        page = _parse_xsp_page(response)
        if page is None:
            messages.log(
                "malformed Files.GetDirectory response for {0}".format(path),
                xbmc.LOGERROR,
            )
            return []
        tracks, end, total = page
        paths.extend(tracks)
        if end >= total:
            return paths
        start = end


def _prefer_special_musicplaylists(path: str) -> str:
    """Rewrite an absolute ``.xsp`` path back to a ``special://`` form.

    ``Files.GetDirectory`` only accepts a handful of protocol roots or a
    registered, shareable media source (source-verified,
    ``CFileUtils::RemoteAccessAllowed`` in ``xbmc/utils/FileUtils.cpp``) --
    real device testing found it rejects an arbitrary absolute path with
    ``Invalid params``, even one pointing at Kodi's own default smart-playlist
    save location, because Kodi's settings file-browse dialog already
    resolves it down to a plain absolute path before it ever reaches this
    addon's settings. ``special://`` itself is on the allow-list, so undoing
    that resolution -- when ``path`` falls under it -- is enough to make Kodi
    accept the same ``.xsp`` it just rejected.

    Deliberately keyed off ``special://profile/playlists/music/``, not the
    more obvious ``special://musicplaylists/`` alias: a second real-device
    finding showed the latter translates to a ``multipath://`` union of this
    path *and* ``special://profile/playlists/mixed/``, not a single real
    directory -- ``translatePath`` returns that multipath URI verbatim, which
    can never prefix-match a resolved absolute path. ``special://profile/``
    is on ``RemoteAccessAllowed``'s allow-list in its own right, so the
    narrower, single root works just as well as a rewrite target.

    Args:
        path: The ``.xsp`` file's own path, as read from settings.

    Returns:
        ``path`` rewritten to start with ``special://profile/playlists/music/``
        when it falls under that root's resolved location; unchanged
        otherwise (a `.xsp` living under a different, already-registered,
        shareable source does not need this -- see ``RemoteAccessAllowed``'s
        own source-match branch).
    """
    root = xbmcvfs.translatePath(_MUSIC_PLAYLISTS_ROOT)
    if not root.endswith("/"):
        root += "/"
    if path.startswith(root):
        return _MUSIC_PLAYLISTS_ROOT + path[len(root) :]
    return path


def _parse_xsp_page(response: str) -> Optional[Tuple[List[str], int, int]]:
    """Parse one ``Files.GetDirectory`` JSON-RPC response page.

    Args:
        response: The raw JSON-RPC response string.

    Returns:
        A tuple of (this page's file paths, the window's end, the grand
        total), or None on any JSON-RPC error or malformed shape.
    """
    try:
        parsed = json.loads(response)
        if "error" in parsed:
            return None
        result = parsed["result"]
        limits = result["limits"]
        tracks = [
            item["file"]
            for item in result["files"]
            if item.get("filetype") == "file" and item.get("file")
        ]
        return tracks, int(limits["end"]), int(limits["total"])
    except (KeyError, TypeError, ValueError):
        return None


_MUSIC_SMARTPLAYLIST_TYPE = "songs"
_LEGACY_MUSIC_SMARTPLAYLIST_TYPE = "music"
_SMARTPLAYLIST_ROOT_TAG = "smartplaylist"


def is_music_smartplaylist(path: str) -> bool:
    """Whether a ``.xsp`` file's root ``<smartplaylist type="...">`` is music.

    Kodi accepts several smart-playlist types (source-verified,
    ``CSmartPlaylist::readName()`` in ``xbmc/playlists/SmartPlayList.cpp``):
    ``songs``, ``albums``, ``artists``, ``movies``, ``tvshows``, ``episodes``,
    ``musicvideos``, ``mixed``, plus the legacy alias ``music`` (Kodi itself
    normalizes this to ``songs``). Only ``songs``/``music`` is guaranteed to
    resolve to individual playable *audio* tracks through
    :func:`resolve_xsp`'s ``Files.GetDirectory`` call -- ``movies``,
    ``musicvideos`` and ``mixed`` can return real, playable *video* files
    that would otherwise slip into ``bgm.m3u`` undetected (``resolve_xsp``'s
    own ``filetype == "file"`` filter cannot tell a video file from an audio
    one).

    Args:
        path: The ``.xsp`` file to inspect.

    Returns:
        True for ``<smartplaylist type="songs">`` (or the legacy
        ``type="music">``); False for any other type, and for a file that is
        missing, unreadable, not valid XML, or not rooted at
        ``<smartplaylist>`` -- failing closed, consistent with this module's
        other format checks.
    """
    content = _read_text(path)
    if content is None:
        messages.log("unreadable .xsp file: {0}".format(path), xbmc.LOGERROR)
        return False
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        messages.log("malformed .xsp file: {0}".format(path), xbmc.LOGERROR)
        return False
    if root.tag != _SMARTPLAYLIST_ROOT_TAG:
        messages.log(
            "{0} is not a Kodi smart playlist (root element is <{1}>)".format(
                path, root.tag
            ),
            xbmc.LOGERROR,
        )
        return False
    kind = root.get("type", "")
    if kind == _LEGACY_MUSIC_SMARTPLAYLIST_TYPE:
        kind = _MUSIC_SMARTPLAYLIST_TYPE
    if kind != _MUSIC_SMARTPLAYLIST_TYPE:
        messages.log(
            '{0} is a smartplaylist type="{1}", not a music (songs) playlist'.format(
                path, kind
            ),
            xbmc.LOGWARNING,
        )
        return False
    return True


def write_m3u(tracks: List[str], destination: str) -> bool:
    """Write a bare ``.m3u``: one absolute path per line, UTF-8.

    Written to a temporary sibling of ``destination`` first and only moved
    into place once every line is confirmed written, so a failure can never
    leave a truncated playlist behind. Nothing downstream would catch one: a
    half-written ``bgm.m3u`` is still non-empty, so :func:`_has_content`
    accepts it and the session plays a silently shortened playlist instead of
    reporting that it could not build one (FR-010).

    The sibling lives in the same directory rather than a system temp dir, so
    the move stays on one filesystem and every step goes through ``xbmcvfs``
    (D-009).

    Args:
        tracks: Absolute track paths, in playback order.
        destination: File to create or overwrite.

    Returns:
        True when the whole playlist was written and put in place; False on a
        failed or partial write, which leaves any existing ``destination``
        untouched -- content and mtime alike.
    """
    partial = destination + PARTIAL_SUFFIX
    if not _write_all(tracks, partial):
        messages.log(
            "failed to write playlist {0}; left the previous one in place".format(
                destination
            ),
            xbmc.LOGERROR,
        )
        _discard(partial)
        return False
    if not _replace(partial, destination):
        messages.log(
            "failed to put the newly written playlist in place at {0}; left the "
            "previous one in place".format(destination),
            xbmc.LOGERROR,
        )
        _discard(partial)
        return False
    return True


def _write_all(tracks: List[str], path: str) -> bool:
    """Write every track line to ``path``, checking each write individually.

    Real Kodi's ``xbmcvfs.File.write()`` returns ``False`` on failure instead
    of raising, and a failed open yields a working-looking handle rather than
    an exception (D-009's second addendum), so the first ``write()`` is also
    what reports an open that never succeeded. The ``try``/``except`` stays as
    a second line of defense for whichever failure mode a given VFS backend
    does raise.

    Args:
        tracks: Absolute track paths, in playback order.
        path: File to create or overwrite.

    Returns:
        True when every line was written and the finished file is as long as
        the lines written into it; False otherwise.
    """
    lines = [track + "\n" for track in tracks]
    try:
        handle = xbmcvfs.File(path, "w")
        try:
            for line in lines:
                if not handle.write(line):
                    return False
        finally:
            handle.close()
    except (OSError, IOError):
        return False
    return _is_fully_written("".join(lines), path)


def _is_fully_written(content: str, path: str) -> bool:
    """Whether ``path`` ended up holding at least as many bytes as ``content``.

    Catches a short write that reported success anyway -- the same class of
    quietly-lying failure D-009's second addendum records for ``write()``'s
    return value.

    Args:
        content: Everything that was written, as one string.
        path: File to measure.

    Returns:
        True when the file exists and is at least ``content``'s UTF-8 byte
        length. Kodi writes the bytes verbatim, so "longer" cannot mean a
        lost track; it can only come from a backend translating line endings.
    """
    if not xbmcvfs.exists(path):
        return False
    return bool(xbmcvfs.Stat(path).st_size() >= len(content.encode("utf-8")))


def _replace(partial: str, destination: str) -> bool:
    """Move a fully written playlist over the one it replaces.

    Args:
        partial: The finished temporary file.
        destination: File to replace.

    Returns:
        True when ``destination`` is now the file ``partial`` held.
    """
    if xbmcvfs.rename(partial, destination):
        return True
    # Unverified across the platforms this addon targets: Kodi's own docs do
    # not say whether rename() overwrites an existing destination, and the
    # underlying behavior differs by OS. Being defensive rather than
    # trusting it -- clear the destination and retry -- costs one call on a
    # backend that would have overwritten it anyway.
    xbmcvfs.delete(destination)
    return bool(xbmcvfs.rename(partial, destination))


def _discard(path: str) -> None:
    """Remove a leftover temporary file, if one survived.

    Args:
        path: Temporary file to remove.
    """
    if xbmcvfs.exists(path):
        xbmcvfs.delete(path)


def resolve(source: BgmSource) -> Optional[str]:
    """Absolute path of the playlist to hand to ``PlayMedia``.

    Assumes the source is worth trying -- ``config.validate`` classifies why a
    source is unusable; this returns ``None`` on any failure rather than
    raising, so a bad source never fails the slideshow (FR-010).

    A directory is scanned, and a ``.pls``/``.xsp`` playlist is resolved to
    its own track list (FR-008: Kodi's own ``playoffset`` resume never
    advances past track 1 for these two formats on a real device); both are
    flattened into the same derived ``bgm.m3u``. A plain ``.m3u`` playlist is
    handed through untouched, unchanged from before this resolution existed.

    Args:
        source: The configured BGM source.

    Returns:
        The playlist path, or None when nothing playable could be resolved.
    """
    if source.kind == DIRECTORY:
        return _resolve_derived(source, scan_directory)
    if source.playlist_format == PlaylistFormat.PLS:
        return _resolve_derived(source, parse_pls)
    if source.playlist_format == PlaylistFormat.XSP:
        return _resolve_derived(source, resolve_xsp)
    return _resolve_playlist(source)


def _resolve_playlist(source: BgmSource) -> Optional[str]:
    """Hand a user-chosen playlist file through if it holds anything.

    Args:
        source: A :data:`PLAYLIST` source.

    Returns:
        The playlist path, or None when it is missing or empty.
    """
    if not _has_content(source.path):
        messages.log(
            "playlist unreadable or empty: {0}".format(source.path), xbmc.LOGERROR
        )
        return None
    return source.path


def _resolve_derived(
    source: BgmSource, get_tracks: Callable[[str], List[str]]
) -> Optional[str]:
    """Resolve a source whose tracks are derived into ``bgm.m3u``.

    Shared by a directory source and a ``.pls``/``.xsp`` playlist source
    alike -- all three obtain a track list from ``source.path`` in their own
    way and then go through the same rebuild (:func:`_regenerate`); only how
    the track list is produced differs. No separate validity check follows it:
    :func:`_regenerate` reports success only once ``bgm.m3u`` provably holds a
    non-empty list, having either size-verified its own write or confirmed the
    identical list was already there.

    The track list is re-derived on every call, never cached across slideshow
    starts (D-009's 2026-09-15 revision). The mtime cache this replaces
    protected a recursive walk that measured well inside SC-001's budget
    anyway, and it could not help the one case that is genuinely slow -- the
    first start after any settings change pays the identical cold walk
    regardless. What it did cost was permanent: a directory whose *contents*
    changed without a settings change went on serving a playlist missing the
    new music indefinitely, with nothing the user could do to explain or
    correct it (SC-005). :func:`_regenerate` keeps re-deriving cheap by
    leaving the file alone when the list it produced is the one already there.

    Args:
        source: The source to resolve.
        get_tracks: Callable producing the ordered track list from
            ``source.path``.

    Returns:
        The derived playlist path, or None when nothing playable resulted.
    """
    m3u_path = os.path.join(lib.profile_dir, M3U_FILENAME)
    if not _regenerate(source, m3u_path, get_tracks):
        return None
    return m3u_path


def _regenerate(
    source: BgmSource, m3u_path: str, get_tracks: Callable[[str], List[str]]
) -> bool:
    """Re-derive the track list from ``source`` and rewrite ``bgm.m3u``.

    How long ``get_tracks`` took is logged at ``LOGDEBUG`` with the resulting
    track count. Timed here rather than inside :func:`scan_directory` so it
    covers all three resolvers uniformly -- a slow ``.xsp`` JSON-RPC
    round-trip is worth seeing just as much as a slow directory walk. The
    measurements that retired the mtime cache were synthetic and from one
    machine, so this line is how a genuinely slow real-world source shows up
    in ``kodi.log`` rather than being guessed at.

    Args:
        source: The source to resolve.
        m3u_path: Derived playlist location.
        get_tracks: Callable producing the ordered track list from
            ``source.path``.

    Returns:
        True when ``bgm.m3u`` holds the freshly derived track list, whether
        this call wrote it or found the same list already there. False when
        no tracks resolved, and when writing them out failed -- in which case
        any previous ``bgm.m3u`` is left exactly as it was (:func:`write_m3u`).
    """
    started = time.monotonic()
    tracks = get_tracks(source.path)
    messages.log(
        "resolved {0} tracks from {1} in {2:.1f} ms".format(
            len(tracks), source.path, (time.monotonic() - started) * 1000
        ),
        xbmc.LOGDEBUG,
    )
    if not tracks:
        messages.log(
            "no usable tracks resolved from {0}".format(source.path), xbmc.LOGERROR
        )
        return False
    if _already_holds(tracks, m3u_path):
        return True
    xbmcvfs.mkdirs(os.path.dirname(m3u_path))
    return write_m3u(tracks, m3u_path)


def _already_holds(tracks: List[str], m3u_path: str) -> bool:
    """Whether ``m3u_path`` already holds exactly ``tracks``, in that order.

    Compared as content, deliberately not against a stored hash: the
    comparison is exact, it needs no second persisted artifact that could
    drift out of step with the playlist itself, and reading back a few
    thousand short path strings costs far less than the walk or query that
    just produced them.

    This is what makes re-deriving the track list on every slideshow start
    cheap. An unchanged list skips :func:`write_m3u` entirely, so the file
    and its mtime are left untouched rather than rewritten to identical
    bytes.

    Args:
        tracks: The freshly derived track list.
        m3u_path: Derived playlist location, which need not exist yet.

    Returns:
        True when the file's lines are exactly ``tracks``; False when they
        differ in any way, and when the file is absent or unreadable -- in
        which case it has to be written regardless.
    """
    content = _read_text(m3u_path)
    return content is not None and content.splitlines() == tracks


def _has_content(path: str) -> bool:
    """Whether a file exists and is not empty (D-009: never ``os.path``).

    Args:
        path: File to check.

    Returns:
        True when the file exists and holds at least one byte.
    """
    return bool(xbmcvfs.exists(path)) and xbmcvfs.Stat(path).st_size() > 0
