"""Script Mode entry point: one process per slideshow (FR-001, FR-004, D-007).

Launched by the ``<onload>`` hook the service installs into the active skin's
``SlideShow.xml``, so this runs exactly when a slideshow window opens and
returns when that slideshow exits. Everything it does -- reading settings,
starting background music, waiting the slideshow out, tearing down -- belongs
to :class:`resources.lib.session.SlideshowSession`; keeping this file to a
construction and a call is what keeps the dependency graph in
contracts/modules.md one-directional.
"""

from resources.lib.session import SlideshowSession


def main() -> None:
    """Build the session and run it. One process per slideshow."""
    SlideshowSession().run()


if __name__ == "__main__":
    main()
