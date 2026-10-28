"""Shared package and dashboard release version."""

# Python uses .dev1 for the first development release; the UI calls it demo.1.
__version__ = "0.1.0.dev1"
DISPLAY_VERSION = "v" + __version__.replace(".dev", "-demo.")
