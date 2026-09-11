#!/usr/bin/env python3
"""Classify a Sports Big Board commit as frontend-only or backend-required.

The fast path is intentionally conservative. Only known GitHub Pages surfaces
may skip the Compute Engine deployment. Unknown paths fall back to a full
backend deploy so a newly introduced runtime dependency cannot be missed.
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
from pathlib import Path

ROOT_FRONTEND = {
    "index.html",
    "backend.html",
    "media-audit.html",
    "media-audit-probe.html",
    "canonical-shadow.html",
    "styles.css",
    "app.js",
    "core-model.js",
    "api-runtime.js",
}
FRONTEND_PREFIXES = ("ui/", "architecture/")
FRONTEND_SUFFIXES = (".js", ".css", ".html", ".json")
PAGES_BUILD_PREFIX = "cloud/github-pages/"
DATA_ONLY = {
    "data/sports-ticker.json",
    "data/sports-ticker.txt",
    "data/sports-ticker-run-log.json",
}


def is_frontend_only_path(path: str) -> bool:
    path = path.strip().replace("\\", "/").lstrip("./")
    if not path:
        return True
    if path in DATA_ONLY:
        return True
    if path in ROOT_FRONTEND:
        return True
    if path.startswith(PAGES_BUILD_PREFIX):
        return path.endswith((".py", ".js", ".css", ".html", ".json", ".yml", ".yaml"))
    if path.startswith(FRONTEND_PREFIXES):
        # architecture/VERSION is deliberately excluded because release identity
        # must remain coupled to the backend semantic version.
        return path.endswith(FRONTEND_SUFFIXES)
    return False


def classify(paths: list[str]) -> tuple[bool, list[str], list[str]]:
    normalized = [p.strip().replace("\\", "/").lstrip("./") for p in paths if p.strip()]
    backend = [p for p in normalized if not is_frontend_only_path(p)]
    frontend = [p for p in normalized if is_frontend_only_path(p)]
    return bool(backend), frontend, backend


def changed_files(before: str, after: str) -> list[str]:
    before = (before or "").strip()
    after = (after or "HEAD").strip()
    if before and set(before) != {"0"}:
        cmd = ["git", "diff", "--name-only", before, after]
    else:
        cmd = ["git", "diff", "--name-only", f"{after}^", after]
    proc = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def write_output(path: str, key: str, value: str) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", default="")
    parser.add_argument("--after", default="HEAD")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--force-backend", action="store_true")
    args = parser.parse_args()

    paths = changed_files(args.before, args.after)
    backend_required, frontend, backend = classify(paths)
    if args.force_backend:
        backend_required = True

    print("Changed files:")
    for path in paths:
        print(f"  {path}")
    print(f"Frontend-safe files: {len(frontend)}")
    print(f"Backend/unknown files: {len(backend)}")
    for path in backend:
        print(f"  backend-required: {path}")
    print("Deployment scope:", "FULL_BACKEND" if backend_required else "FRONTEND_ONLY")

    write_output(args.github_output, "backend_required", "true" if backend_required else "false")
    write_output(args.github_output, "frontend_only", "false" if backend_required else "true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
