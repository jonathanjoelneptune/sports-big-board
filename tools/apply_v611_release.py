#!/usr/bin/env python3
"""Atomic checkout materializer for Sports Big Board v6.1.1.

The repository deploy lane materializes one semantic release inside each clean
GitHub Actions checkout. v6.1.1 therefore collapses the active 5.5.0/6.0.0/6.1.0
source generations to 6.1.1, installs the certification-hardening layer, extends
verification, preserves the operator navigation links, and materializes the
versioned controller map required by release-integrity checks.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

OLD_VALUES = ("5.5.0", "6.0.0", "6.1.0")
NEW = "6.1.1"
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".json", ".sh", ".yml", ".yaml"}
ACTIVE_DIRS = ("ui", "architecture", "sbb", "tests", "cloud", ".github")


def active_files(root: Path):
    seen = set()
    for path in sorted(root.iterdir()):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            seen.add(path)
            yield path
    checker = root / "tools" / "check_release_version.py"
    if checker.is_file() and checker not in seen:
        seen.add(checker)
        yield checker
    for dirname in ACTIVE_DIRS:
        base = root / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            rel = path.relative_to(root)
            if any(part.startswith("sports-big-board-v") for part in rel.parts):
                continue
            if path not in seen:
                seen.add(path)
                yield path


def patch_init(root: Path, dry=False):
    path = root / "sbb" / "__init__.py"
    text = path.read_text(encoding="utf-8")
    if "_install_canonical_certification_v611()" in text:
        return False
    block = (
        "\n\n# v6.1.1: canonical certification contradiction gate + adapter hardening.\n"
        "# Shadow-only: known production contradictions revoke certification; production authority remains unchanged.\n"
        "from .canonical_certification_v611 import install as _install_canonical_certification_v611\n"
        "_install_canonical_certification_v611()\n"
    )
    if not dry:
        path.write_text(text.rstrip() + block, encoding="utf-8")
    return True


def patch_verify(root: Path, dry=False):
    path = root / "VERIFY.sh"
    text = path.read_text(encoding="utf-8")
    additions = []
    if "tests/test_v611_canonical_hardening.py" not in text:
        additions.append("python3 tests/test_v611_canonical_hardening.py")
    if "tests/test_v611_runtime_responsiveness.py" not in text:
        additions.append("python3 tests/test_v611_runtime_responsiveness.py")
    if "sbb/canonical_certification_v611.py" not in text:
        additions.append("python3 -m py_compile sbb/canonical_certification_v611.py")
    if not additions:
        return False
    marker = "python3 tools/check_release_version.py"
    block = "\n".join(additions)
    if marker in text:
        text = text.replace(marker, marker + "\n" + block, 1)
    else:
        text = text.rstrip() + "\n" + block + "\n"
    if not dry:
        path.write_text(text, encoding="utf-8")
    return True


def patch_legacy_v610_test(root: Path, dry=False):
    """Advance the v6.1 release-surface test to the active v6.1.1 materializer."""
    path = root / "tests" / "test_v610_canonical_certification.py"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    old = "assert w.count('python3 tools/apply_v610_release.py') >= 4"
    new = "assert w.count('python3 tools/apply_v611_release.py') >= 4"
    if old not in text:
        return False
    if not dry:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def patch_frontend(root: Path, dry=False):
    path = root / "index.html"
    text = path.read_text(encoding="utf-8")
    original = text
    if 'href="canonical-shadow.html"' not in text:
        media = '<a class="backend-inspector-link" href="media-audit.html" target="_blank" rel="noopener" title="Open Media Health Audit">MEDIA AUDIT</a>'
        backend = '<a class="backend-inspector-link" href="backend.html" target="_blank" rel="noopener" title="Open Backend Inspector">BACKEND</a>'
        insert = (
            '\n    <a class="backend-inspector-link" href="canonical-shadow.html" target="_blank" rel="noopener" title="Open Canonical Slate Validation Console">CANONICAL</a>'
            '\n    <a class="backend-inspector-link" id="sbbCanonicalHealthLink" href="#" target="_blank" rel="noopener" title="Open Canonical Backend Health">CANON HEALTH</a>'
            '\n    <a class="backend-inspector-link" id="sbbCanonicalCertHealthLink" href="#" target="_blank" rel="noopener" title="Open Canonical Certification Adapter Health">CERT HEALTH</a>'
        )
        if media in text:
            text = text.replace(media, media + insert, 1)
        elif backend in text:
            text = text.replace(backend, backend + insert, 1)
        else:
            raise SystemExit("ERROR: index.html backend navigation anchor not found; refusing unsafe patch")
    if "sbbCanonicalCertHealthLink" in text and "SBB_CANONICAL_DIAGNOSTIC_LINKS" not in text:
        script = '''\n<script>\n(()=>{\n  'use strict';\n  window.SBB_CANONICAL_DIAGNOSTIC_LINKS='6.1.1';\n  const base=String(window.SBB_CONFIG?.apiBase||'').replace(/\\/$/,'');\n  const links=[['sbbCanonicalHealthLink','/api/canonical/health'],['sbbCanonicalCertHealthLink','/api/canonical/certification/health']];\n  for(const [id,path] of links){const a=document.getElementById(id);if(a){a.href=base?base+path:path;}}\n})();\n</script>\n'''
        if "</body>" not in text:
            raise SystemExit("ERROR: index.html missing </body>; refusing unsafe diagnostics patch")
        text = text.replace("</body>", script + "</body>", 1)
    if text != original:
        if not dry:
            path.write_text(text, encoding="utf-8")
        return True
    return False


def materialize_controller_map(root: Path, dry=False):
    target = root / f"CONTROLLER-REGION-MAP-v{NEW}.md"
    sources = [
        root / "CONTROLLER-REGION-MAP-v6.1.0.md",
        root / "CONTROLLER-REGION-MAP-v6.0.0.md",
        root / "CONTROLLER-REGION-MAP-v5.5.0.md",
    ]
    source = next((x for x in sources if x.is_file()), None)
    if source is None:
        if target.is_file():
            return False
        raise SystemExit("ERROR: no controller-region-map source is available for v6.1.1 materialization")
    text = source.read_text(encoding="utf-8")
    for old in OLD_VALUES:
        text = text.replace(old, NEW)
    if target.is_file() and target.read_text(encoding="utf-8") == text:
        return False
    if not dry:
        target.write_text(text, encoding="utf-8")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    version = root / "VERSION"
    arch_version = root / "architecture" / "VERSION"
    if not version.is_file():
        raise SystemExit("ERROR: Sports Big Board VERSION file not found")
    current = version.read_text(encoding="utf-8").strip()
    if current not in set(OLD_VALUES) | {NEW}:
        raise SystemExit(f"ERROR: expected source release 5.5.0/6.0.0/6.1.0/6.1.1, found {current!r}")
    required = [
        root / "sbb" / "canonical_shadow_v600.py",
        root / "sbb" / "canonical_certification_v610.py",
        root / "sbb" / "canonical_certification_v611.py",
        root / "tests" / "test_v600_canonical_shadow.py",
        root / "tests" / "test_v610_canonical_certification.py",
        root / "tests" / "test_v611_canonical_hardening.py",
        root / "tests" / "test_v611_runtime_responsiveness.py",
        root / "canonical-shadow.html",
    ]
    missing = [str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing:
        raise SystemExit("ERROR: v6.1.1 web overlay incomplete: " + ", ".join(missing))

    patch_changes = []
    if patch_init(root, args.dry_run):
        patch_changes.append(root / "sbb" / "__init__.py")
    if patch_verify(root, args.dry_run):
        patch_changes.append(root / "VERIFY.sh")
    if patch_legacy_v610_test(root, args.dry_run):
        patch_changes.append(root / "tests" / "test_v610_canonical_certification.py")
    if patch_frontend(root, args.dry_run):
        patch_changes.append(root / "index.html")

    changes = []
    for path in active_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rendered = text
        for old in OLD_VALUES:
            rendered = rendered.replace(old, NEW)
        if rendered == text:
            continue
        changes.append(path)
        if not args.dry_run:
            path.write_text(rendered, encoding="utf-8")

    doc_changes = []
    if materialize_controller_map(root, args.dry_run):
        doc_changes.append(root / f"CONTROLLER-REGION-MAP-v{NEW}.md")

    authority_changes = []
    for path in (version, arch_version):
        if not path.is_file() or path.read_text(encoding="utf-8").strip() != NEW:
            authority_changes.append(path)
            if not args.dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(NEW + "\n", encoding="utf-8")

    changed = list(dict.fromkeys(changes + doc_changes + authority_changes + patch_changes))
    print(f"Sports Big Board v6.1.1 release materialization -> {NEW}")
    print(f"Files {'that would change' if args.dry_run else 'changed'}: {len(changed)}")
    for path in changed:
        print("  " + str(path.relative_to(root)))

    if args.dry_run or args.skip_check:
        return 0
    checker = root / "tools" / "check_release_version.py"
    if checker.is_file():
        result = subprocess.run([sys.executable, str(checker)], cwd=root)
        if result.returncode:
            print("ERROR: release-integrity checker failed after v6.1.1 materialization", file=sys.stderr)
            return result.returncode
        print("PASS: release identity is synchronized at 6.1.1")
    else:
        print("WARNING: release-integrity checker not found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
