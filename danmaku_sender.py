#!/usr/bin/env python3
"""Official launcher for 弹幕补档机 RS (DanmakuSender)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from danmaku_rs.ui.app import main

if __name__ == "__main__":
    main()
