#!/usr/bin/env python3
"""Fast pre-deploy rehearsal for Sports Big Board releases.

This preflight intentionally checks executable/source contracts only. Historical
CHANGED-FILES-vX.X.X.txt bookkeeping is never read, required, or validated.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterable

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()


def fail(message: str) -> None:
    print(f"FAIL: deploy rehearsal: {message}", file=sys.stderr)
    raise SystemExit(1)


def _resolve_path_expr(node: ast.AST, root: Path) -> Path | None:
    if isinstance(node,ast.Name) and node.id=='ROOT': return root
    if isinstance(node,ast.Constant) and isinstance(node.value,str): return Path(node.value)
    if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Div):
        left=_resolve_path_expr(node.left,root);right=_resolve_path_expr(node.right,root)
        if left is None or right is None:return None
        return left/right
    return None


def _read_text_binding(expr: ast.AST, root: Path) -> Path | None:
    if not isinstance(expr,ast.Call) or not isinstance(expr.func,ast.Attribute) or expr.func.attr!='read_text': return None
    return _resolve_path_expr(expr.func.value,root)


def _target_names(node: ast.AST) -> list[str]:
    if isinstance(node,ast.Name):return [node.id]
    if isinstance(node,(ast.Tuple,ast.List)):
        out=[]
        for elt in node.elts:out.extend(_target_names(elt))
        return out
    return []


def _assignment_binding(stmt: ast.stmt, root: Path):
    if isinstance(stmt,ast.Assign):
        names=[]
        for target in stmt.targets:names.extend(_target_names(target))
        return (names,_read_text_binding(stmt.value,root)) if names else None
    if isinstance(stmt,ast.AnnAssign):
        names=_target_names(stmt.target)
        return (names,_read_text_binding(stmt.value,root) if stmt.value is not None else None) if names else None
    return None


def _direct_module_bindings(tree: ast.Module, root: Path):
    bindings={}
    for stmt in tree.body:
        row=_assignment_binding(stmt,root)
        if row:
            names,path=row
            for name in names:bindings[name]=path
    return bindings


def _iter_scope_statements(statements: Iterable[ast.stmt]):
    for stmt in statements:
        yield stmt
        if isinstance(stmt,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda)):continue
        child_lists=[]
        if isinstance(stmt,(ast.If,ast.For,ast.AsyncFor,ast.While)):child_lists.extend([stmt.body,stmt.orelse])
        elif isinstance(stmt,(ast.With,ast.AsyncWith)):child_lists.append(stmt.body)
        elif isinstance(stmt,ast.Try):
            child_lists.extend([stmt.body,stmt.orelse,stmt.finalbody]);child_lists.extend(h.body for h in stmt.handlers)
        for child in child_lists:yield from _iter_scope_statements(child)


def _assertion_problem(node,bindings,test_path,root,cache):
    if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute):return False,None
    if node.func.attr not in {'assertIn','assertNotIn'} or len(node.args)<2:return False,None
    needle_node,haystack_node=node.args[0],node.args[1]
    if not (isinstance(needle_node,ast.Constant) and isinstance(needle_node.value,str)):return False,None
    if not isinstance(haystack_node,ast.Name) or haystack_node.id not in bindings:return False,None
    source_path=bindings[haystack_node.id]
    if source_path is None:return False,None
    if not source_path.is_file():
        try:shown=source_path.relative_to(root)
        except ValueError:shown=source_path
        return True,f"{test_path.relative_to(root)}:{node.lineno}: contract source missing: {shown}"
    if source_path not in cache:cache[source_path]=source_path.read_text(encoding='utf-8')
    needle=needle_node.value;present=needle in cache[source_path];expected=node.func.attr=='assertIn'
    if present==expected:return True,None
    relation='missing required token' if expected else 'contains forbidden token'
    short=needle.replace('\n','\\n')[:180]
    return True,f"{test_path.relative_to(root)}:{node.lineno}: {relation} in {source_path.relative_to(root)}: {short!r}"


def _scan_scope(statements,inherited,test_path,root,cache):
    bindings=dict(inherited);checked=0;problems=[]
    for stmt in _iter_scope_statements(statements):
        row=_assignment_binding(stmt,root)
        if row:
            names,path=row
            for name in names:bindings[name]=path
        nodes=[stmt] if isinstance(stmt,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) else list(ast.walk(stmt))
        for node in nodes:
            ok,problem=_assertion_problem(node,bindings,test_path,root,cache)
            checked+=int(ok)
            if problem:problems.append(problem)
    return checked,problems


def static_source_contract_scan(root: Path=ROOT):
    tests_dir=root/'tests'
    if not tests_dir.is_dir():fail('tests/ directory is missing')
    files_scanned=0;assertions_checked=0;problems=[]
    for test_path in sorted(tests_dir.glob('test_*.py')):
        files_scanned+=1
        try:tree=ast.parse(test_path.read_text(encoding='utf-8'),filename=str(test_path))
        except SyntaxError as exc:
            problems.append(f'{test_path.relative_to(root)}:{exc.lineno}: syntax error: {exc.msg}');continue
        global_bindings=_direct_module_bindings(tree,root);cache={}
        module_statements=[s for s in tree.body if not isinstance(s,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]
        count,found=_scan_scope(module_statements,global_bindings,test_path,root,cache);assertions_checked+=count;problems.extend(found)
        for top in tree.body:
            if isinstance(top,(ast.FunctionDef,ast.AsyncFunctionDef)):
                count,found=_scan_scope(top.body,global_bindings,test_path,root,cache);assertions_checked+=count;problems.extend(found)
            elif isinstance(top,ast.ClassDef):
                class_bindings=dict(global_bindings)
                for stmt in top.body:
                    row=_assignment_binding(stmt,root)
                    if row:
                        names,path=row
                        for name in names:class_bindings[name]=path
                for member in top.body:
                    if isinstance(member,(ast.FunctionDef,ast.AsyncFunctionDef)):
                        count,found=_scan_scope(member.body,class_bindings,test_path,root,cache);assertions_checked+=count;problems.extend(found)
    if problems:
        print('Deploy rehearsal found stale source-contract guards:',file=sys.stderr)
        for problem in problems[:50]:print(f'  - {problem}',file=sys.stderr)
        if len(problems)>50:print(f'  ... and {len(problems)-50} more',file=sys.stderr)
        raise SystemExit(1)
    return files_scanned,assertions_checked


def workflow_chain_check():
    workflow=ROOT/'.github'/'workflows'/'deploy-pages.yml'
    if not workflow.is_file():fail('production workflow .github/workflows/deploy-pages.yml is missing')
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
    if missing:fail('production workflow contract missing: '+', '.join(missing))


def unittest_discovery_contract_check():
    count=0;problems=[]
    for test_path in sorted((ROOT/'tests').glob('test_v43*.py')):
        try:tree=ast.parse(test_path.read_text(encoding='utf-8'),filename=str(test_path))
        except SyntaxError as exc:fail(f'{test_path.relative_to(ROOT)}:{exc.lineno}: syntax error: {exc.msg}')
        bare=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_')]
        if bare:problems.append(f"{test_path.relative_to(ROOT)} has bare test functions ignored by unittest: "+', '.join(n.name for n in bare))
        for node in tree.body:
            if not isinstance(node,ast.ClassDef):continue
            is_case=any(isinstance(base,ast.Attribute) and base.attr=='TestCase' for base in node.bases) or any(isinstance(base,ast.Name) and base.id=='TestCase' for base in node.bases)
            if is_case:count+=sum(1 for child in node.body if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef)) and child.name.startswith('test_'))
    if problems:
        for problem in problems:print(f'FAIL: deploy rehearsal: {problem}',file=sys.stderr)
        raise SystemExit(1)
    return count


def main():
    workflow_chain_check()
    discoverable_tests=unittest_discovery_contract_check()
    files_scanned,assertions_checked=static_source_contract_scan()
    print(f'PASS: deploy rehearsal executable/source contracts at v{VERSION} ({files_scanned} test files, {assertions_checked} exact source assertions, {discoverable_tests} v4.3 unittest tests; CHANGED-FILES ignored)')

if __name__=='__main__':main()
