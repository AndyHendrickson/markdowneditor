"""mdedit - a pure-Python Markdown editor and renderer.

Standard library only.  Nothing in this package opens a socket, resolves a
host name or reads a URL; every file it touches is a local path the user
picked.
"""

__version__ = "1.0.0"
__all__ = ["parser", "tkrender", "html_export", "app"]
