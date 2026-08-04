#!/usr/bin/env python3
"""Launcher: ``python mdedit.py [file.md]``."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mdedit.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
