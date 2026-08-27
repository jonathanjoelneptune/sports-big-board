#!/usr/bin/env python3
"""Build a complete, upload-ready Sports Big Board release bundle from the manifest."""
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/'dist'

def run(cmd):
    print('+',' '.join(map(str,cmd)))
    subprocess.run(cmd,cwd=ROOT,check=True)

run([sys.executable,'tools/check_release_manifest.py'])
manifest=json.loads((ROOT/'release-manifest.json').read_text(encoding='utf-8'))
release=str(manifest['release'])
name=f'sports-big-board-v{release}-upload-ready'
out=DIST/name
zip_path=DIST/f'{name}.zip'
if out.exists(): shutil.rmtree(out)
DIST.mkdir(parents=True,exist_ok=True)
out.mkdir(parents=True)

hash_rows=[]
for rel in manifest['requiredFiles']:
    src=ROOT/rel; dst=out/rel
    dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src,dst)
    digest=hashlib.sha256(dst.read_bytes()).hexdigest()
    hash_rows.append(f'{digest}  {rel}')
(out/'SHA256SUMS.txt').write_text('\n'.join(hash_rows)+'\n',encoding='utf-8')
(out/'UPLOAD-README.txt').write_text(
    f'Sports Big Board v{release} ATOMIC UPLOAD BUNDLE\n\n'
    'This directory was generated only after release-manifest validation.\n'
    'Upload/copy the ENTIRE directory tree at the exact repository paths.\n'
    'Do not select individual test files or a subset of this bundle.\n'
    'After upload, run: bash VERIFY.sh\n',encoding='utf-8')
if zip_path.exists(): zip_path.unlink()
with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as zf:
    for p in sorted(out.rglob('*')):
        if p.is_file(): zf.write(p,p.relative_to(out.parent))
print(f'PASS: built {zip_path}')
