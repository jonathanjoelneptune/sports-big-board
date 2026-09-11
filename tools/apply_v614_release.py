#!/usr/bin/env python3
"""Sports Big Board v6.1.4 smoke-test reliability + frontend cache materializer."""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path

BASE="6.1.3"
NEW="6.1.4"
TEXT_SUFFIXES={".py",".js",".css",".html",".json",".sh",".yml",".yaml"}
ACTIVE_DIRS=("ui","architecture","sbb","tests","cloud",".github")

def active_files(root):
    seen=set()
    for p in sorted(root.iterdir()):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:
            seen.add(p); yield p
    checker=root/"tools"/"check_release_version.py"
    if checker.is_file() and checker not in seen:
        seen.add(checker); yield checker
    for dirname in ACTIVE_DIRS:
        base=root/dirname
        if not base.is_dir(): continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES: continue
            rel=p.relative_to(root)
            if any(part.startswith("sports-big-board-v") for part in rel.parts): continue
            if p not in seen:
                seen.add(p); yield p

def run_base(root):
    (root/"VERSION").write_text(BASE+"\n",encoding="utf-8")
    arch=root/"architecture"/"VERSION"; arch.parent.mkdir(parents=True,exist_ok=True); arch.write_text(BASE+"\n",encoding="utf-8")
    subprocess.run([sys.executable,str(root/"tools"/"apply_v613_release.py"),"--skip-check"],cwd=root,check=True)

def patch_validation(root):
    p=root/"sbb"/"canonical_validation_v612.py"
    text=p.read_text(encoding="utf-8")
    old='''def _install_into_server():
    global _DIAG
    deadline=_now()+120; server=None; engine=None
    while _now()<deadline:
        server=sys.modules.get("__main__"); engine=v611.engine()
        if server and engine and hasattr(server,"Handler") and hasattr(server,"send_json"): break
        time.sleep(0.25)
    if not server or not engine: return
'''
    new='''def _install_into_server():
    global _DIAG
    # v6.1.4: cold starts can outlive the old 120-second installer deadline.
    # This is a daemon thread, so keep waiting until both the certification
    # engine and HTTP handler exist instead of permanently losing this API.
    server=None; engine=None
    while True:
        server=sys.modules.get("__main__"); engine=v611.engine()
        if server and engine and hasattr(server,"Handler") and hasattr(server,"send_json"):
            break
        time.sleep(0.5)
'''
    if new not in text:
        if old not in text: raise SystemExit("ERROR: canonical validation startup anchor missing")
        p.write_text(text.replace(old,new,1),encoding="utf-8")

def patch_pages(root):
    p=root/"cloud"/"github-pages"/"build_pages.py"
    text=p.read_text(encoding="utf-8")
    if "import json, os, re, shutil, sys" not in text:
        if "import json, os, shutil, sys" not in text: raise SystemExit("ERROR: pages import anchor missing")
        text=text.replace("import json, os, shutil, sys","import json, os, re, shutil, sys",1)
    marker="""for directory in ('architecture','ui'):
    shutil.copytree(root/directory,out/directory)
"""
    block="""for directory in ('architecture','ui'):
    shutil.copytree(root/directory,out/directory)

# v6.1.4: frontend-only commits may keep the backend semantic VERSION unchanged.
# Add the Git SHA as an independent asset cache generation.
build_sha=(os.environ.get('GITHUB_SHA') or '').strip()[:12]
if build_sha:
    versioned_asset=re.compile(r"(\\?v=\\d+\\.\\d+\\.\\d+)(?=[\"'])")
    for page in out.glob('*.html'):
        source=page.read_text(encoding='utf-8')
        rendered=versioned_asset.sub(lambda m:f"{m.group(1)}&b={build_sha}",source)
        if rendered!=source:
            page.write_text(rendered,encoding='utf-8')
"""
    if "independent asset cache generation" not in text:
        if marker not in text: raise SystemExit("ERROR: pages copy anchor missing")
        text=text.replace(marker,block,1)
    p.write_text(text,encoding="utf-8")

def patch_verify(root):
    p=root/"VERIFY.sh"; text=p.read_text(encoding="utf-8")
    cmd="python3 tests/test_v614_smoke_reliability.py"
    if cmd not in text:
        anchor="python3 tools/check_release_version.py"
        if anchor not in text: raise SystemExit("ERROR: VERIFY anchor missing")
        p.write_text(text.replace(anchor,anchor+"\n"+cmd,1),encoding="utf-8")

def promote(root):
    for p in active_files(root):
        try: source=p.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        rendered=source.replace(BASE,NEW)
        if rendered!=source: p.write_text(rendered,encoding="utf-8")
    for p in (root/"VERSION",root/"architecture"/"VERSION"):
        p.parent.mkdir(parents=True,exist_ok=True); p.write_text(NEW+"\n",encoding="utf-8")

def controller(root):
    src=root/f"CONTROLLER-REGION-MAP-v{BASE}.md"; dst=root/f"CONTROLLER-REGION-MAP-v{NEW}.md"
    if not src.is_file(): raise SystemExit(f"ERROR: missing {src.name}")
    dst.write_text(src.read_text(encoding="utf-8").replace(BASE,NEW),encoding="utf-8")

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--dry-run",action="store_true"); ap.add_argument("--skip-check",action="store_true")
    args=ap.parse_args(argv); root=Path(__file__).resolve().parents[1]
    current=(root/"VERSION").read_text(encoding="utf-8").strip()
    if current!=NEW: raise SystemExit(f"ERROR: expected VERSION {NEW}, got {current!r}")
    required=[root/"tools"/"apply_v613_release.py",root/"sbb"/"canonical_validation_v612.py",root/"cloud"/"github-pages"/"build_pages.py",root/"tests"/"test_v614_smoke_reliability.py"]
    missing=[str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing: raise SystemExit("ERROR: incomplete v6.1.4 release: "+", ".join(missing))
    if args.dry_run:
        print("v6.1.4: preserve v6.1.3, make validation installer wait for readiness, add frontend commit cache generation"); return 0
    run_base(root); patch_validation(root); patch_pages(root); patch_verify(root); promote(root); controller(root)
    print("Sports Big Board v6.1.4 materialized")
    print("Canonical validation installer: readiness-based, no 120-second give-up")
    print("Frontend asset cache generation: Git commit SHA")
    if args.skip_check: return 0
    subprocess.run([sys.executable,str(root/"tools"/"check_release_version.py")],cwd=root,check=True)
    print("PASS: deployment-critical release identity is synchronized at 6.1.4")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
