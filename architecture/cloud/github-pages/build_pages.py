#!/usr/bin/env python3
from pathlib import Path
import json, os, shutil, sys
from urllib.parse import urlparse

root=Path(__file__).resolve().parents[2]
out=Path(sys.argv[2] if len(sys.argv)>2 else root/'.pages-dist')
api=(sys.argv[1] if len(sys.argv)>1 else '').strip().rstrip('/')
parsed=urlparse(api)
if not api or parsed.scheme!='https' or not parsed.netloc:
    raise SystemExit('SBB_API_BASE_URL must be a public https:// URL')
if out.exists(): shutil.rmtree(out)
out.mkdir(parents=True)
for name in ('index.html','backend.html','styles.css','app.js','core-model.js','api-runtime.js'):
    shutil.copy2(root/name,out/name)
for directory in ('architecture','ui'):
    shutil.copytree(root/directory,out/directory)
# Soundtrack metadata ships with Pages, but the ~400 MB MP3 library never does.
# Audio remains in private Cloud Storage and is reached through the backend signed/proxy boundary.
(out/'assets'/'soundtrack').mkdir(parents=True,exist_ok=True)
shutil.copy2(root/'assets'/'soundtrack'/'manifest.json',out/'assets'/'soundtrack'/'manifest.json')
soundtrack=(os.environ.get('SBB_SOUNDTRACK_BASE_URL') or '').strip().rstrip('/')
if not soundtrack:
    soundtrack=f'{api}/api/soundtrack'
config=f"window.SBB_CONFIG = Object.freeze({{apiBase:{json.dumps(api)},soundtrackBase:{json.dumps(soundtrack)},soundtrackTransport:'private-gcs',deployment:'github-pages'}});\n"
(out/'config.js').write_text(config,encoding='utf-8')
(out/'.nojekyll').write_text('',encoding='utf-8')
print(f'Built GitHub Pages frontend -> {out}')
print(f'API base -> {api}')
print('Backend Inspector -> backend.html')
