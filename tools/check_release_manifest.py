#!/usr/bin/env python3
"""Atomic release-manifest gate for Sports Big Board.

Runs before every other release check. It verifies that the manual-upload file set
is complete, all local cache generations match VERSION, VERIFY wires every named
test, and historical Python regression tests do not pin VERSION to an older release.
"""
from __future__ import annotations
import ast
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MANIFEST_PATH=ROOT/'release-manifest.json'
errors=[]

def fail(msg): errors.append(msg)

def read(rel):
    p=ROOT/rel
    if not p.is_file():
        fail(f'missing required release file: {rel}')
        return ''
    try: return p.read_text(encoding='utf-8')
    except Exception as exc:
        fail(f'unreadable required release file {rel}: {exc}')
        return ''

if not MANIFEST_PATH.is_file():
    raise SystemExit('RELEASE MANIFEST CHECK FAILED\n - missing release-manifest.json')
try:
    manifest=json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
except Exception as exc:
    raise SystemExit(f'RELEASE MANIFEST CHECK FAILED\n - invalid release-manifest.json: {exc}')

release=str(manifest.get('release','')).strip()
if not re.fullmatch(r'\d+\.\d+\.\d+',release): fail(f'invalid manifest release: {release!r}')
if manifest.get('atomic') is not True: fail('manifest atomic must be true')
if int(manifest.get('schemaVersion') or 0)!=1: fail(f"unsupported manifest schemaVersion: {manifest.get('schemaVersion')!r}")

required=list(dict.fromkeys(str(x) for x in manifest.get('requiredFiles',[]) if str(x).strip()))
if not required: fail('manifest requiredFiles is empty')
texts={rel:read(rel) for rel in required}
version=texts.get('VERSION',read('VERSION')).strip()
if release and version!=release: fail(f'VERSION {version!r} does not match manifest release {release!r}')

for rel,spec in (manifest.get('contracts') or {}).items():
    text=texts.get(rel)
    if text is None: text=read(rel)
    for token in spec.get('required',[]) or []:
        if str(token) not in text: fail(f"{rel}: missing required token {token!r}")
    for token in spec.get('forbidden',[]) or []:
        if str(token) in text: fail(f"{rel}: contains forbidden token {token!r}")

# Every executable local cache-busted JS/CSS reference must be exactly this release.
index=texts.get('index.html',read('index.html'))
for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    if found!=release: fail(f'index.html: stale cache generation {found} on {asset}; expected {release}')
    if not (ROOT/asset).is_file(): fail(f'index.html: referenced local asset is missing: {asset}')

verify=texts.get('VERIFY.sh',read('VERIFY.sh'))
if 'python3 tools/check_release_manifest.py' not in verify:
    fail('VERIFY.sh does not execute tools/check_release_manifest.py')
for test_path in re.findall(r'(tests/[A-Za-z0-9_.\-/]+\.(?:js|py))',verify):
    if not (ROOT/test_path).is_file(): fail(f'VERIFY.sh references missing test: {test_path}')

# Catch the exact regression that caused the v4.4.4 upload loop: an old test may
# preserve a behavior baseline, but it may not assert that VERSION equals an older
# literal semantic version. Version-aware tests must derive the current release.
def semver_literal(node):
    return node.value if isinstance(node,ast.Constant) and isinstance(node.value,str) and re.fullmatch(r'\d+\.\d+\.\d+',node.value) else None
for test_path in sorted((ROOT/'tests').glob('test_*.py')):
    try: tree=ast.parse(test_path.read_text(encoding='utf-8'),filename=str(test_path))
    except SyntaxError as exc:
        fail(f'{test_path.relative_to(ROOT)}:{exc.lineno}: syntax error: {exc.msg}')
        continue
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute) or node.func.attr not in {'assertEqual','assertMultiLineEqual'} or len(node.args)<2:
            continue
        a,b=node.args[:2]
        literal=None
        if isinstance(a,ast.Name) and a.id=='VERSION': literal=semver_literal(b)
        elif isinstance(b,ast.Name) and b.id=='VERSION': literal=semver_literal(a)
        if literal and literal!=release:
            fail(f'{test_path.relative_to(ROOT)}:{node.lineno}: hard-coded VERSION {literal} is stale; derive current VERSION or assert a minimum baseline')

changed=f'CHANGED-FILES-v{release}.txt'
changed_text=texts.get(changed,read(changed))
for rel in required:
    if rel not in changed_text: fail(f'{changed}: required manual-upload file not listed: {rel}')

if errors:
    print('RELEASE MANIFEST CHECK FAILED')
    for err in errors: print(' -',err)
    raise SystemExit(1)
print(f'PASS: v{release} atomic manual-upload manifest is complete ({len(required)} files)')
