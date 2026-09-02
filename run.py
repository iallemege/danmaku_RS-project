#!/usr/bin/env python3
"""Alias for danmaku_sender.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from danmaku_rs.ui.app import main

if __name__ == "__main__":
    main()
