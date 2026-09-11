#!/usr/bin/env python3
"""Deterministic hash of files whose bytes require a cloud backend restart.

Frontend-only assets are intentionally excluded. The hash is computed after the
release materializer runs, so any materializer change that affects backend bytes
is naturally reflected by the files selected here.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path, PurePosixPath


def include_path(rel: PurePosixPath) -> bool:
    parts = rel.parts
    if not parts:
        return False
    if rel.as_posix() == "VERSION":
        return True
    if rel.as_posix() in {"server.py", "media_audit_service.py", "assets/soundtrack/manifest.json"}:
        return True
    if parts[0] == "sbb":
        return "__pycache__" not in parts and not rel.name.endswith((".pyc", ".pyo"))
    if len(parts) >= 2 and parts[0] == "cloud" and parts[1] in {"gcp", "vm"}:
        return True
    if rel.as_posix() == "tools/ensure_history_v4.py":
        return True
    if len(parts) == 1 and rel.name.startswith("requirements") and rel.suffix == ".txt":
        return True
    return False


def selected_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = PurePosixPath(path.relative_to(root).as_posix())
        if include_path(rel):
            yield path, rel


def digest(root: Path) -> str:
    h = hashlib.sha256()
    count = 0
    for path, rel in selected_files(root):
        count += 1
        h.update(rel.as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    if count == 0:
        raise RuntimeError("backend payload selection is empty")
    return h.hexdigest()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = Path(argv[0]).resolve() if argv else Path(__file__).resolve().parents[1]
    print(digest(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
