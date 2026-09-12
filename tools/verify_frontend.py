#!/usr/bin/env python3
"""Fast verification for frontend-only Sports Big Board deployments.

This checks the exact static artifact GitHub Pages will publish without running
backend/canonical/database/VM regression suites that cannot be affected by a
frontend-only commit.
"""
from __future__ import annotations

import json
import os
from html.parser import HTMLParser
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PAGES_BUILDER = ROOT / "cloud" / "github-pages" / "build_pages.py"
CLASSIFIER = ROOT / "tools" / "classify_deploy_scope.py"
REQUIRED_ROOT = {
    "index.html",
    "backend.html",
    "media-audit.html",
    "media-audit-probe.html",
    "canonical-shadow.html",
    "styles.css",
    "app.js",
    "core-model.js",
    "api-runtime.js",
    "config.js",
    ".nojekyll",
}
LIVE_HTML_ENTRYPOINTS = {
    "index.html",
    "backend.html",
    "media-audit.html",
    "media-audit-probe.html",
    "canonical-shadow.html",
}
FORBIDDEN_RUNTIME_SUFFIXES = {".py", ".pyc", ".sqlite", ".sqlite3", ".sh"}


class AssetRefs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key in {"src", "href"} and value:
                self.refs.append((tag, value))


def run(*args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=ROOT, check=True, env=env)


def validate_local_references(out: Path) -> int:
    checked = 0
    # Only root HTML files are live Pages entrypoints. Nested HTML under
    # architecture/ is historical/reference content, not a launch surface.
    for name in sorted(LIVE_HTML_ENTRYPOINTS):
        html = out / name
        parser = AssetRefs()
        parser.feed(html.read_text(encoding="utf-8"))
        for _tag, raw in parser.refs:
            split = urlsplit(raw)
            if split.scheme or split.netloc or raw.startswith(("#", "data:", "mailto:", "javascript:")):
                continue
            rel = split.path
            if not rel or Path(rel).suffix.lower() not in {".js", ".css", ".html", ".json"}:
                continue
            if rel.startswith("/"):
                target = out / rel.lstrip("/")
            else:
                target = html.parent / rel
            target = target.resolve()
            try:
                target.relative_to(out.resolve())
            except ValueError as exc:
                raise AssertionError(f"frontend reference escapes Pages artifact: {html.name} -> {raw}") from exc
            assert target.exists(), f"missing frontend reference: {html.relative_to(out)} -> {raw}"
            checked += 1
    return checked


def live_runtime_leaks(out: Path) -> list[str]:
    """Return backend/runtime files exposed through live static surfaces.

    architecture/ intentionally contains historical/reference snapshots,
    including Python and shell files. They are inert documentation artifacts.
    The live root and ui/ runtime surfaces must remain static-only.
    """
    candidates = [p for p in out.iterdir() if p.is_file()]
    ui = out / "ui"
    if ui.exists():
        candidates.extend(p for p in ui.rglob("*") if p.is_file())
    return sorted(
        p.relative_to(out).as_posix()
        for p in candidates
        if p.suffix.lower() in FORBIDDEN_RUNTIME_SUFFIXES
    )


def main() -> int:
    print("Sports Big Board focused frontend verification")

    # Compile the two Python utilities used by the frontend-only CI path.
    py_compile.compile(str(PAGES_BUILDER), doraise=True)
    py_compile.compile(str(CLASSIFIER), doraise=True)

    with tempfile.TemporaryDirectory(prefix="sbb-pages-verify-") as temp:
        out = Path(temp) / "pages"
        env = os.environ.copy()
        env.pop("SBB_SOUNDTRACK_BASE_URL", None)
        run(sys.executable, str(PAGES_BUILDER), "https://frontend-verify.invalid", str(out), env=env)

        missing = sorted(name for name in REQUIRED_ROOT if not (out / name).exists())
        assert not missing, f"Pages artifact missing required files: {missing}"
        assert (out / "ui").is_dir(), "Pages artifact missing ui/"
        assert (out / "architecture").is_dir(), "Pages artifact missing architecture/"

        config = (out / "config.js").read_text(encoding="utf-8")
        assert "https://frontend-verify.invalid" in config
        assert "deployment:'github-pages'" in config

        js_files = sorted(out.rglob("*.js"))
        assert js_files, "Pages artifact contains no JavaScript"
        for path in js_files:
            run("node", "--check", str(path))

        json_files = sorted(out.rglob("*.json"))
        for path in json_files:
            json.loads(path.read_text(encoding="utf-8"))

        refs = validate_local_references(out)
        forbidden = live_runtime_leaks(out)
        assert not forbidden, f"backend/runtime files leaked into live Pages surfaces: {forbidden}"

        print(f"PASS: {len(js_files)} shipped JavaScript files parse")
        print(f"PASS: {len(json_files)} shipped JSON files parse")
        print(f"PASS: {refs} live-entrypoint asset references resolve")
        print("PASS: live root/ui surfaces contain no backend/runtime files")

    print("PASS: focused frontend verification complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
