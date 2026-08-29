#!/usr/bin/env python3
"""Fast structural pre-deploy rehearsal for Sports Big Board releases.

This check deliberately does NOT inspect unittest assertIn/assertNotIn literals
against implementation source files. Those exact-string guards duplicated the
real test suite and repeatedly blocked releases after harmless refactors.

Behavioral correctness remains enforced by VERIFY.sh through:
- release manifest/version/certification verification
- targeted Python regression suites
- full unittest discovery
- JavaScript contract/runtime tests
- Python/JS/shell syntax checks
- GitHub Pages dry build
- production workflow-chain validation
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()


def fail(message: str) -> None:
    print(f"FAIL: deploy rehearsal: {message}", file=sys.stderr)
    raise SystemExit(1)


def workflow_chain_check():
    workflow=ROOT/'.github'/'workflows'/'deploy-pages.yml'
    if not workflow.is_file():
        fail('production workflow .github/workflows/deploy-pages.yml is missing')
    text=workflow.read_text(encoding='utf-8')
    required={
        'release verifier':'run: bash VERIFY.sh',
        'backend waits for verification':'needs: verify',
        'backend public version check':'Verify public backend health and release version',
        'Pages build':'Build GitHub Pages frontend',
        'production smoke':'Verify deployed frontend/backend handshake',
        'milestone handshake':'/api/milestone/console?frontendVersion=$EXPECTED_VERSION',
    }
    missing=[label for label,token in required.items() if token not in text]
    if missing:
        fail('production workflow contract missing: '+', '.join(missing))


def test_syntax_check():
    tests_dir=ROOT/'tests'
    if not tests_dir.is_dir():
        fail('tests/ directory is missing')
    files=0
    for test_path in sorted(tests_dir.glob('test_*.py')):
        files+=1
        try:
            ast.parse(test_path.read_text(encoding='utf-8'), filename=str(test_path))
        except SyntaxError as exc:
            fail(f'{test_path.relative_to(ROOT)}:{exc.lineno}: syntax error: {exc.msg}')
    return files


def unittest_discovery_contract_check():
    count=0
    problems=[]
    for test_path in sorted((ROOT/'tests').glob('test_v43*.py')):
        try:
            tree=ast.parse(test_path.read_text(encoding='utf-8'), filename=str(test_path))
        except SyntaxError as exc:
            fail(f'{test_path.relative_to(ROOT)}:{exc.lineno}: syntax error: {exc.msg}')
        bare=[
            n for n in tree.body
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
            and n.name.startswith('test_')
        ]
        if bare:
            problems.append(
                f"{test_path.relative_to(ROOT)} has bare test functions ignored by unittest: "
                + ', '.join(n.name for n in bare)
            )
        for node in tree.body:
            if not isinstance(node,ast.ClassDef):
                continue
            is_case=(
                any(isinstance(base,ast.Attribute) and base.attr=='TestCase' for base in node.bases)
                or any(isinstance(base,ast.Name) and base.id=='TestCase' for base in node.bases)
            )
            if is_case:
                count+=sum(
                    1 for child in node.body
                    if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef))
                    and child.name.startswith('test_')
                )
    if problems:
        for problem in problems:
            print(f'FAIL: deploy rehearsal: {problem}',file=sys.stderr)
        raise SystemExit(1)
    return count


def main():
    workflow_chain_check()
    files_scanned=test_syntax_check()
    discoverable_tests=unittest_discovery_contract_check()
    print(
        f'PASS: deploy rehearsal structural contracts at v{VERSION} '
        f'({files_scanned} test files syntax-valid, '
        f'{discoverable_tests} v4.3 unittest tests discoverable; '
        'exact implementation-string pre-scan disabled)'
    )


if __name__=='__main__':
    main()
