#!/usr/bin/env python3
"""Fast pre-deploy rehearsal for Sports Big Board releases.

This deliberately runs before the expensive regression suite.  It catches a
class of release blockers that has repeatedly appeared during v4.x hardening:
Python source-contract tests that still require an exact token removed or moved
by the candidate release.  It also validates the release overlay manifest and
production workflow dependency chain.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def fail(message: str) -> None:
    print(f"FAIL: deploy rehearsal: {message}", file=sys.stderr)
    raise SystemExit(1)


def _resolve_path_expr(node: ast.AST, root: Path) -> Path | None:
    if isinstance(node, ast.Name) and node.id == "ROOT":
        return root
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return Path(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _resolve_path_expr(node.left, root)
        right = _resolve_path_expr(node.right, root)
        if left is None or right is None:
            return None
        return left / right
    return None


def _read_text_binding(expr: ast.AST, root: Path) -> Path | None:
    # NAME=(ROOT/'app.js').read_text(...)
    if not isinstance(expr, ast.Call) or not isinstance(expr.func, ast.Attribute):
        return None
    if expr.func.attr != "read_text":
        return None
    return _resolve_path_expr(expr.func.value, root)


def static_source_contract_scan() -> tuple[int, int]:
    tests_dir = ROOT / "tests"
    if not tests_dir.is_dir():
        fail("tests/ directory is missing")
    files_scanned = 0
    assertions_checked = 0
    problems: list[str] = []
    for test_path in sorted(tests_dir.glob("test_*.py")):
        files_scanned += 1
        try:
            tree = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path))
        except SyntaxError as exc:
            problems.append(f"{test_path.relative_to(ROOT)}:{exc.lineno}: syntax error: {exc.msg}")
            continue
        bindings: dict[str, Path] = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            path = _read_text_binding(value, ROOT) if value is not None else None
            if path is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = path
        cache: dict[Path, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"assertIn", "assertNotIn"} or len(node.args) < 2:
                continue
            needle_node, haystack_node = node.args[0], node.args[1]
            if not (isinstance(needle_node, ast.Constant) and isinstance(needle_node.value, str)):
                continue
            if not isinstance(haystack_node, ast.Name) or haystack_node.id not in bindings:
                continue
            source_path = bindings[haystack_node.id]
            if not source_path.is_file():
                problems.append(
                    f"{test_path.relative_to(ROOT)}:{node.lineno}: contract source missing: "
                    f"{source_path.relative_to(ROOT) if source_path.is_absolute() else source_path}"
                )
                continue
            if source_path not in cache:
                cache[source_path] = source_path.read_text(encoding="utf-8")
            haystack = cache[source_path]
            needle = needle_node.value
            assertions_checked += 1
            present = needle in haystack
            expected = node.func.attr == "assertIn"
            if present != expected:
                relation = "missing required token" if expected else "contains forbidden token"
                short = needle.replace("\n", "\\n")[:180]
                problems.append(
                    f"{test_path.relative_to(ROOT)}:{node.lineno}: {relation} in "
                    f"{source_path.relative_to(ROOT)}: {short!r}"
                )
    if problems:
        print("Deploy rehearsal found stale source-contract guards:", file=sys.stderr)
        for problem in problems[:50]:
            print(f"  - {problem}", file=sys.stderr)
        if len(problems) > 50:
            print(f"  ... and {len(problems)-50} more", file=sys.stderr)
        raise SystemExit(1)
    return files_scanned, assertions_checked


def overlay_manifest_check() -> int:
    manifest = ROOT / f"CHANGED-FILES-v{VERSION}.txt"
    if not manifest.exists():
        # Not every historical release carries an overlay manifest, but current
        # upload-style releases do.  Absence is informational rather than fatal.
        return 0
    rows = [x.strip() for x in manifest.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not rows:
        fail(f"{manifest.name} is empty")
    missing = [row for row in rows if not (ROOT / row).is_file()]
    if missing:
        fail(f"{manifest.name} lists missing files: {', '.join(missing)}")
    if "VERSION" not in rows:
        fail(f"{manifest.name} must include VERSION")
    return len(rows)


def workflow_chain_check() -> None:
    workflow = ROOT / ".github" / "workflows" / "deploy-pages.yml"
    if not workflow.is_file():
        fail("production workflow .github/workflows/deploy-pages.yml is missing")
    text = workflow.read_text(encoding="utf-8")
    required = {
        "release verifier": "run: bash VERIFY.sh",
        "backend waits for verification": "needs: verify",
        "backend public version check": "Verify public backend health and release version",
        "Pages build": "Build GitHub Pages frontend",
        "production smoke": "Verify deployed frontend/backend handshake",
        "milestone handshake": "/api/milestone/console?frontendVersion=$EXPECTED_VERSION",
    }
    missing = [label for label, token in required.items() if token not in text]
    if missing:
        fail("production workflow contract missing: " + ", ".join(missing))



def unittest_discovery_contract_check() -> int:
    """Certification/hardening tests must be discoverable by unittest.

    VERIFY.sh intentionally uses unittest discover. Bare pytest-style test functions
    are silently skipped there, which previously let v4.3.3/v4.3.4 guards exist on
    disk without participating in the deploy gate.
    """
    count = 0
    problems: list[str] = []
    for test_path in sorted((ROOT / "tests").glob("test_v43*.py")):
        tree = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path))
        bare = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")]
        if bare:
            problems.append(f"{test_path.relative_to(ROOT)} has bare test functions ignored by unittest: " + ", ".join(n.name for n in bare))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                if any(isinstance(base, ast.Attribute) and base.attr == "TestCase" for base in node.bases) or any(isinstance(base, ast.Name) and base.id == "TestCase" for base in node.bases):
                    count += sum(1 for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_"))
    if problems:
        for problem in problems:
            print(f"FAIL: deploy rehearsal: {problem}", file=sys.stderr)
        raise SystemExit(1)
    return count

def main() -> None:
    workflow_chain_check()
    manifest_count = overlay_manifest_check()
    discoverable_tests = unittest_discovery_contract_check()
    files_scanned, assertions_checked = static_source_contract_scan()
    print(
        f"PASS: deploy rehearsal static contracts at v{VERSION} "
        f"({files_scanned} test files, {assertions_checked} exact source assertions, "
        f"{discoverable_tests} v4.3 unittest tests, {manifest_count or 'no'} overlay-manifest files)"
    )


if __name__ == "__main__":
    main()
