#!/usr/bin/env python3
"""Sports Big Board v6.1.11 canonical validation console bootstrap materializer."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = "6.1.10"
NEW = "6.1.11"
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".sh", ".yml", ".yaml"}
ACTIVE_DIRS = ("ui", "architecture", "sbb", "tests", "cloud", ".github")


def active_files(root):
    seen = set()
    for p in sorted(root.iterdir()):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:
            seen.add(p)
            yield p
    checker = root / "tools" / "check_release_version.py"
    if checker.is_file() and checker not in seen:
        seen.add(checker)
        yield checker
    for dirname in ACTIVE_DIRS:
        base = root / dirname
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
                continue
            rel = p.relative_to(root)
            if any(part.startswith("sports-big-board-v") for part in rel.parts):
                continue
            if p not in seen:
                seen.add(p)
                yield p


def run_base(root):
    (root / "VERSION").write_text(BASE + "\n", encoding="utf-8")
    arch = root / "architecture" / "VERSION"
    arch.parent.mkdir(parents=True, exist_ok=True)
    arch.write_text(BASE + "\n", encoding="utf-8")
    tools = str(root / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import apply_v6110_release
    rc = apply_v6110_release.main(["--skip-check"])
    if rc not in (None, 0):
        raise SystemExit(rc)


def patch_install_chain(root):
    path = root / "sbb" / "__init__.py"
    text = path.read_text(encoding="utf-8")
    integrity_call = "_install_canonical_run_integrity_v6110()"
    bootstrap_call = "_install_canonical_console_bootstrap_v6111()"
    if integrity_call not in text:
        raise SystemExit(f"ERROR: canonical install-chain prerequisite missing: {integrity_call}")
    if bootstrap_call not in text:
        block = (
            "\n\n# v6.1.11: canonical validation console bootstrap/performance repair.\n"
            "# Shadow-only: one certification-health roll-up per snapshot + persisted startup summary.\n"
            "from .canonical_console_bootstrap_v6111 import install as _install_canonical_console_bootstrap_v6111\n"
            "_install_canonical_console_bootstrap_v6111()"
        )
        text = text.replace(integrity_call, integrity_call + block, 1)
        path.write_text(text, encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    if text.index(integrity_call) >= text.index(bootstrap_call):
        raise SystemExit("ERROR: canonical console bootstrap must install after v6.1.10 run integrity")


def patch_verify(root):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    marker = "python3 tools/check_release_version.py"
    commands = (
        "python3 tests/test_v6111_canonical_console_bootstrap.py",
        "python3 -m py_compile sbb/canonical_console_bootstrap_v6111.py",
    )
    if marker not in text:
        raise SystemExit("ERROR: VERIFY release checker anchor missing")
    additions = [cmd for cmd in commands if cmd not in text]
    if additions:
        text = text.replace(marker, marker + "\n" + "\n".join(additions), 1)
        path.write_text(text, encoding="utf-8")


def patch_console_warmup(root):
    path = root / "canonical-shadow.html"
    text = path.read_text(encoding="utf-8")
    old = "if(!x.ready&&x.ok&& !x.days){$('updated').textContent='Validation cache warming; retrying…';setTimeout(refresh,3000);return}"
    new = (
        "if(!x.ready&&x.ok&&!x.days){"
        "$('cards').innerHTML=[card('Snapshot','Warming'),card('Backend','Connected'),card('Production authority','NO')].join('');"
        "$('findings').innerHTML='<div class=\"trace WARN\"><b>INITIAL SNAPSHOT BUILDING</b> Backend is connected and the validation read model is warming. This page will populate automatically.</div>';"
        "$('captureState').textContent='initial validation snapshot building';"
        "$('updated').textContent='Backend connected; validation snapshot warming; retrying automatically…';"
        "setTimeout(refresh,3000);return}"
    )
    if old in text:
        text = text.replace(old, new, 1)
    # Persisted bootstrap snapshots already contain summary/window collection keys,
    # so the normal renderer can show them immediately. Make the status explicit.
    old_state = "$('captureState').textContent=`snapshot ${new Date((x.capturedAt||0)*1000).toLocaleTimeString()} · build ${(x.buildSeconds??'cached')}s`;"
    new_state = "$('captureState').textContent=x.bootstrap?`persisted snapshot ${new Date((x.capturedAt||0)*1000).toLocaleTimeString()} · live rebuild in progress`:`snapshot ${new Date((x.capturedAt||0)*1000).toLocaleTimeString()} · build ${(x.buildSeconds??'cached')}s`;"
    if old_state in text:
        text = text.replace(old_state, new_state, 1)
    path.write_text(text, encoding="utf-8")


def promote(root):
    for p in active_files(root):
        try:
            source = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rendered = source.replace(BASE, NEW)
        if rendered != source:
            p.write_text(rendered, encoding="utf-8")
    for p in (root / "VERSION", root / "architecture" / "VERSION"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(NEW + "\n", encoding="utf-8")


def controller(root):
    src = root / f"CONTROLLER-REGION-MAP-v{BASE}.md"
    dst = root / f"CONTROLLER-REGION-MAP-v{NEW}.md"
    if not src.is_file():
        raise SystemExit(f"ERROR: missing {src.name}")
    dst.write_text(src.read_text(encoding="utf-8").replace(BASE, NEW), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-check", action="store_true")
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    current = (root / "VERSION").read_text(encoding="utf-8").strip()
    if current != NEW:
        raise SystemExit(f"ERROR: expected VERSION {NEW}, got {current!r}")
    required = [
        root / "tools" / "apply_v6110_release.py",
        root / "sbb" / "canonical_console_bootstrap_v6111.py",
        root / "tests" / "test_v6111_canonical_console_bootstrap.py",
    ]
    missing = [str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("ERROR: incomplete v6.1.11 release: " + ", ".join(missing))
    if args.dry_run:
        print("v6.1.11: preserve v6.1.10 + parallel lanes and repair canonical validation console bootstrap")
        return 0
    run_base(root)
    patch_install_chain(root)
    patch_verify(root)
    patch_console_warmup(root)
    promote(root)
    controller(root)
    print("Sports Big Board v6.1.11 materialized")
    print("Canonical console: one health roll-up/build + fast initial read + persisted bootstrap summary")
    if args.skip_check:
        return 0
    tools = str(root / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import check_release_version  # noqa: F401 - importing executes release checker
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
