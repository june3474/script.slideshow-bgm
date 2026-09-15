"""Injects the hand-written Kodi fakes into ``sys.modules`` (research.md D-008).

``xbmc``/``xbmcgui``/``xbmcvfs``/``xbmcaddon`` are C++ bindings Kodi provides
at runtime; they cannot be pip-installed. Kodistubs (a dev dependency) *is*
pip-installable and *is* importable, but it is stub-only -- its function
bodies do nothing -- so it must never be what a test actually exercises.

This module is loaded by pytest before collecting any test file in this
directory tree, so registering the fakes in ``sys.modules`` here, at import
time (not inside a fixture), guarantees they win over Kodistubs for every
``import xbmc`` a test or a ``resources.lib`` module performs afterwards.
"""

import importlib.util
import pathlib
import sys
import types
from typing import Iterator

import pytest

_FAKES_DIR = pathlib.Path(__file__).parent / "fakes"


def _install_fake(name: str) -> types.ModuleType:
    """Load ``tests/fakes/<name>.py`` and register it as ``sys.modules[name]``."""
    spec = importlib.util.spec_from_file_location(name, _FAKES_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Order matters only in that none of these fakes import each other, so any
# order is safe; listed alphabetically for stability.
_xbmc = _install_fake("xbmc")
_xbmcaddon = _install_fake("xbmcaddon")
_xbmcgui = _install_fake("xbmcgui")
_xbmcvfs = _install_fake("xbmcvfs")


@pytest.fixture(autouse=True)
def _reset_kodi_fakes() -> Iterator[None]:
    """Reset every fake's shared state before each test, so tests never leak
    volume levels, recorded dialog calls, or settings into one another."""
    _xbmc.world.reset()
    _xbmcgui.calls.reset()
    _xbmcaddon.store.reset()
    yield
