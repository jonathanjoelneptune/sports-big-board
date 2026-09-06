#!/usr/bin/env python3
"""Compatibility entry point for stale v6.1.0 workflow references.

v6.1.1 supersedes the v6.1.0 checkout materializer. If a legacy workflow still
invokes this filename, delegate to the active v6.1.1 materializer instead of
failing because VERSION is already 6.1.1.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target = root / "tools" / "apply_v611_release.py"
    if not target.is_file():
        print(
            "ERROR: legacy apply_v610_release.py was invoked, but "
            "tools/apply_v611_release.py is not present",
            file=sys.stderr,
        )
        return 2
    return subprocess.call([sys.executable, str(target), *sys.argv[1:]], cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
