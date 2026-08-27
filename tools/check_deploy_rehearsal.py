#!/usr/bin/env python3
"""Fast pre-deploy rehearsal for Sports Big Board releases.

This deliberately runs before the expensive regression suite. It catches a
class of release blockers that repeatedly appeared during v4.x hardening:
Python source-contract tests that still require an exact token removed or moved
by the candidate release. It also validates the release overlay manifest,
production workflow dependency chain, and unittest discoverability.

v4.3.4 scope hardening: source aliases are resolved lexically. A local variable
such as ``src`` or ``policy`` belongs only to the test method that assigned it;
it must never inherit a same-named binding from another test method.
"""
from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path
from typing import Iterable

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


def _target_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        out: list[str] = []
        for elt in node.elts:
            out.extend(_target_names(elt))
        return out
    return []


def _assignment_binding(stmt: ast.stmt, root: Path) -> tuple[list[str], Path | None] | None:
    """Return names assigned by a simple statement and its direct read_text path.

    A non-read_text assignment returns ``None`` for the path intentionally: it
    shadows any same-named outer/global source alias. This is important for lexical
    correctness when tests reuse common names such as ``src`` and ``policy``.
    """
    if isinstance(stmt, ast.Assign):
        names: list[str] = []
        for target in stmt.targets:
            names.extend(_target_names(target))
        return (names, _read_text_binding(stmt.value, root)) if names else None
    if isinstance(stmt, ast.AnnAssign):
        names = _target_names(stmt.target)
        return (names, _read_text_binding(stmt.value, root) if stmt.value is not None else None) if names else None
    return None


def _direct_module_bindings(tree: ast.Module, root: Path) -> dict[str, Path | None]:
    bindings: dict[str, Path | None] = {}
    for stmt in tree.body:
        row = _assignment_binding(stmt, root)
        if row is None:
            continue
        names, path = row
        for name in names:
            bindings[name] = path
    return bindings


def _iter_scope_statements(statements: Iterable[ast.stmt]) -> Iterable[ast.stmt]:
    """Yield statements in lexical execution order without crossing function scopes.

    We recurse into control-flow bodies because tests sometimes build a source alias
    inside ``with``/``if`` blocks. Nested functions/classes are separate scopes and
    are handled independently by the top-level scanner.
    """
    for stmt in statements:
        yield stmt
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        child_lists: list[list[ast.stmt]] = []
        if isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            child_lists.extend([stmt.body, stmt.orelse])
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            child_lists.append(stmt.body)
        elif isinstance(stmt, ast.Try):
            child_lists.extend([stmt.body, stmt.orelse, stmt.finalbody])
            child_lists.extend(handler.body for handler in stmt.handlers)
        for child in child_lists:
            yield from _iter_scope_statements(child)


def _assertion_problem(
    node: ast.Call,
    bindings: dict[str, Path | None],
    test_path: Path,
    root: Path,
    cache: dict[Path, str],
) -> tuple[bool, str | None]:
    if not isinstance(node.func, ast.Attribute):
        return False, None
    if node.func.attr not in {"assertIn", "assertNotIn"} or len(node.args) < 2:
        return False, None
    needle_node, haystack_node = node.args[0], node.args[1]
    if not (isinstance(needle_node, ast.Constant) and isinstance(needle_node.value, str)):
        return False, None
    if not isinstance(haystack_node, ast.Name) or haystack_node.id not in bindings:
        return False, None
    source_path = bindings[haystack_node.id]
    # The local name may intentionally refer to a derived string/block rather than
    # a directly-read source file. In that case the fast static rehearsal defers to
    # the real unittest assertion instead of guessing the source.
    if source_path is None:
        return False, None
    if not source_path.is_file():
        shown = source_path
        try:
            shown = source_path.relative_to(root)
        except ValueError:
            pass
        return True, f"{test_path.relative_to(root)}:{node.lineno}: contract source missing: {shown}"
    if source_path not in cache:
        cache[source_path] = source_path.read_text(encoding="utf-8")
    haystack = cache[source_path]
    needle = needle_node.value
    present = needle in haystack
    expected = node.func.attr == "assertIn"
    if present == expected:
        return True, None
    relation = "missing required token" if expected else "contains forbidden token"
    short = needle.replace("\n", "\\n")[:180]
    return True, (
        f"{test_path.relative_to(root)}:{node.lineno}: {relation} in "
        f"{source_path.relative_to(root)}: {short!r}"
    )


def _scan_scope(
    statements: list[ast.stmt],
    inherited: dict[str, Path | None],
    test_path: Path,
    root: Path,
    cache: dict[Path, str],
) -> tuple[int, list[str]]:
    """Scan one lexical function/method scope in statement order."""
    bindings = dict(inherited)
    assertions_checked = 0
    problems: list[str] = []
    for stmt in _iter_scope_statements(statements):
        row = _assignment_binding(stmt, root)
        if row is not None:
            names, path = row
            for name in names:
                bindings[name] = path
        # Do not ast.walk a nested function/class: those use their own bindings.
        nodes = [stmt]
        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes = list(ast.walk(stmt))
        for node in nodes:
            if not isinstance(node, ast.Call):
                continue
            checked, problem = _assertion_problem(node, bindings, test_path, root, cache)
            assertions_checked += int(checked)
            if problem:
                problems.append(problem)
    return assertions_checked, problems


def static_source_contract_scan(root: Path = ROOT) -> tuple[int, int]:
    tests_dir = root / "tests"
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
            problems.append(f"{test_path.relative_to(root)}:{exc.lineno}: syntax error: {exc.msg}")
            continue
        global_bindings = _direct_module_bindings(tree, root)
        cache: dict[Path, str] = {}

        # Module-level assertions use only module bindings.
        module_statements = [s for s in tree.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        count, found = _scan_scope(module_statements, global_bindings, test_path, root, cache)
        assertions_checked += count
        problems.extend(found)

        # Each test method/function gets its own lexical local binding table. This
        # prevents a ``src`` in one test from contaminating ``src`` in another.
        for top in tree.body:
            if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
                count, found = _scan_scope(top.body, global_bindings, test_path, root, cache)
                assertions_checked += count
                problems.extend(found)
            elif isinstance(top, ast.ClassDef):
                class_bindings = dict(global_bindings)
                for stmt in top.body:
                    row = _assignment_binding(stmt, root)
                    if row is not None:
                        names, path = row
                        for name in names:
                            class_bindings[name] = path
                for member in top.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        count, found = _scan_scope(member.body, class_bindings, test_path, root, cache)
                        assertions_checked += count
                        problems.extend(found)

    if problems:
        print("Deploy rehearsal found stale source-contract guards:", file=sys.stderr)
        for problem in problems[:50]:
            print(f"  - {problem}", file=sys.stderr)
        if len(problems) > 50:
            print(f"  ... and {len(problems)-50} more", file=sys.stderr)
        raise SystemExit(1)
    return files_scanned, assertions_checked



def scope_resolution_self_check() -> None:
    """Prove reused local aliases cannot bleed between test methods."""
    with tempfile.TemporaryDirectory(prefix='sbb-deploy-rehearsal-') as td:
        root = Path(td)
        (root / 'tests').mkdir()
        (root / 'alpha.js').write_text('ALPHA_ONLY\n', encoding='utf-8')
        (root / 'beta.js').write_text('BETA_ONLY\n', encoding='utf-8')
        (root / 'upload.sh').write_text('UPLOAD_ONLY\n', encoding='utf-8')
        (root / 'server.py').write_text('SERVER_ONLY\n', encoding='utf-8')
        fixture = '''import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ScopeTests(unittest.TestCase):
    def test_policy_a(self):
        policy=(ROOT/'alpha.js').read_text()
        self.assertIn('ALPHA_ONLY',policy)
        self.assertNotIn('BETA_ONLY',policy)
    def test_policy_b(self):
        policy=(ROOT/'beta.js').read_text()
        self.assertIn('BETA_ONLY',policy)
        self.assertNotIn('ALPHA_ONLY',policy)
    def test_src_upload(self):
        src=(ROOT/'upload.sh').read_text()
        self.assertIn('UPLOAD_ONLY',src)
    def test_src_server(self):
        src=(ROOT/'server.py').read_text()
        self.assertIn('SERVER_ONLY',src)
'''
        (root / 'tests' / 'test_scope.py').write_text(fixture, encoding='utf-8')
        files, assertions = static_source_contract_scan(root)
        if files != 1 or assertions != 6:
            fail(f'scope self-check expected 1 file/6 assertions, got {files}/{assertions}')

def overlay_manifest_check() -> int:
    manifest = ROOT / f"CHANGED-FILES-v{VERSION}.txt"
    if not manifest.exists():
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
    """Certification/hardening tests must be discoverable by unittest."""
    count = 0
    problems: list[str] = []
    for test_path in sorted((ROOT / "tests").glob("test_v43*.py")):
        tree = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path))
        bare = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")]
        if bare:
            problems.append(
                f"{test_path.relative_to(ROOT)} has bare test functions ignored by unittest: "
                + ", ".join(n.name for n in bare)
            )
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            is_case = any(isinstance(base, ast.Attribute) and base.attr == "TestCase" for base in node.bases) or any(
                isinstance(base, ast.Name) and base.id == "TestCase" for base in node.bases
            )
            if is_case:
                count += sum(
                    1
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_")
                )
    if problems:
        for problem in problems:
            print(f"FAIL: deploy rehearsal: {problem}", file=sys.stderr)
        raise SystemExit(1)
    return count


def main() -> None:
    scope_resolution_self_check()
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
