#!/usr/bin/env python3
"""Build DanmakuSender.exe (window title remains 弹幕补档机 RS)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "scripts" / "danmaku_sender.spec"
DIST = ROOT / "dist" / "DanmakuSender.exe"


def main() -> None:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        str(SPEC),
    ]
    subprocess.check_call(cmd, cwd=ROOT)
    if not DIST.exists():
        raise SystemExit(f"build failed: missing {DIST}")
    print(f"built {DIST} ({DIST.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
