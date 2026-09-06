#!/usr/bin/env python3
"""Atomic checkout materializer for Sports Big Board v6.1.2 diagnostics."""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path

OLD_VALUES=("5.5.0","6.0.0","6.1.0","6.1.1")
NEW="6.1.2"
TEXT_SUFFIXES={".py",".js",".css",".html",".json",".sh",".yml",".yaml"}
ACTIVE_DIRS=("ui","architecture","sbb","tests","cloud",".github")

def active_files(root):
    seen=set()
    for p in sorted(root.iterdir()):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES: seen.add(p); yield p
    checker=root/"tools"/"check_release_version.py"
    if checker.is_file() and checker not in seen: seen.add(checker); yield checker
    for d in ACTIVE_DIRS:
        base=root/d
        if not base.is_dir(): continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES: continue
            rel=p.relative_to(root)
            if any(part.startswith("sports-big-board-v") for part in rel.parts): continue
            if p not in seen: seen.add(p); yield p

def patch_init(root,dry=False):
    p=root/"sbb"/"__init__.py"; text=p.read_text(encoding="utf-8")
    if "_install_canonical_validation_v612()" in text: return False
    block=("\n\n# v6.1.2: unified canonical slate validation diagnostics + copy console.\n"
           "# Shadow-only: diagnostics and consistency checks never become production authority.\n"
           "from .canonical_validation_v612 import install as _install_canonical_validation_v612\n"
           "_install_canonical_validation_v612()\n")
    if not dry: p.write_text(text.rstrip()+block,encoding="utf-8")
    return True

def patch_verify(root,dry=False):
    p=root/"VERIFY.sh"; text=p.read_text(encoding="utf-8"); adds=[]
    if "tests/test_v612_canonical_validation_diagnostics.py" not in text: adds.append("python3 tests/test_v612_canonical_validation_diagnostics.py")
    if "sbb/canonical_validation_v612.py" not in text: adds.append("python3 -m py_compile sbb/canonical_validation_v612.py")
    if not adds: return False
    marker="python3 tools/check_release_version.py"; block="\n".join(adds)
    text=text.replace(marker,marker+"\n"+block,1) if marker in text else text.rstrip()+"\n"+block+"\n"
    if not dry: p.write_text(text,encoding="utf-8")
    return True

def patch_legacy_release_tests(root,dry=False):
    changed=False
    for rel in ("tests/test_v610_canonical_certification.py",):
        p=root/rel
        if not p.is_file(): continue
        text=p.read_text(encoding="utf-8"); rendered=text
        rendered=rendered.replace("python3 tools/apply_v610_release.py","python3 tools/apply_v612_release.py")
        rendered=rendered.replace("python3 tools/apply_v611_release.py","python3 tools/apply_v612_release.py")
        if rendered!=text:
            changed=True
            if not dry: p.write_text(rendered,encoding="utf-8")
    return changed

def materialize_controller_map(root,dry=False):
    target=root/f"CONTROLLER-REGION-MAP-v{NEW}.md"
    sources=[root/"CONTROLLER-REGION-MAP-v6.1.1.md",root/"CONTROLLER-REGION-MAP-v6.1.0.md",root/"CONTROLLER-REGION-MAP-v6.0.0.md",root/"CONTROLLER-REGION-MAP-v5.5.0.md"]
    source=next((x for x in sources if x.is_file()),None)
    if source is None:
        if target.is_file(): return False
        raise SystemExit("ERROR: no controller-region-map source available for v6.1.2")
    text=source.read_text(encoding="utf-8")
    for old in OLD_VALUES: text=text.replace(old,NEW)
    if target.is_file() and target.read_text(encoding="utf-8")==text: return False
    if not dry: target.write_text(text,encoding="utf-8")
    return True

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("--dry-run",action="store_true"); ap.add_argument("--skip-check",action="store_true"); args=ap.parse_args(argv)
    root=Path(__file__).resolve().parents[1]; version=root/"VERSION"; arch=root/"architecture"/"VERSION"
    if not version.is_file(): raise SystemExit("ERROR: VERSION missing")
    current=version.read_text(encoding="utf-8").strip()
    if current not in set(OLD_VALUES)|{NEW}: raise SystemExit(f"ERROR: expected source release through 6.1.2, found {current!r}")
    required=[root/"sbb"/"canonical_shadow_v600.py",root/"sbb"/"canonical_certification_v610.py",root/"sbb"/"canonical_certification_v611.py",root/"sbb"/"canonical_validation_v612.py",root/"tests"/"test_v612_canonical_validation_diagnostics.py",root/"canonical-shadow.html"]
    missing=[str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing: raise SystemExit("ERROR: v6.1.2 web overlay incomplete: "+", ".join(missing))
    changed=[]
    if patch_init(root,args.dry_run): changed.append(root/"sbb"/"__init__.py")
    if patch_verify(root,args.dry_run): changed.append(root/"VERIFY.sh")
    if patch_legacy_release_tests(root,args.dry_run): changed.append(root/"tests"/"test_v610_canonical_certification.py")
    for p in active_files(root):
        try: text=p.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        rendered=text
        for old in OLD_VALUES: rendered=rendered.replace(old,NEW)
        if rendered!=text:
            changed.append(p)
            if not args.dry_run: p.write_text(rendered,encoding="utf-8")
    if materialize_controller_map(root,args.dry_run): changed.append(root/f"CONTROLLER-REGION-MAP-v{NEW}.md")
    for p in (version,arch):
        if not p.is_file() or p.read_text(encoding="utf-8").strip()!=NEW:
            changed.append(p)
            if not args.dry_run: p.parent.mkdir(parents=True,exist_ok=True); p.write_text(NEW+"\n",encoding="utf-8")
    changed=list(dict.fromkeys(changed)); print(f"Sports Big Board v6.1.2 release materialization -> {NEW}"); print(f"Files {'that would change' if args.dry_run else 'changed'}: {len(changed)}")
    for p in changed: print("  "+str(p.relative_to(root)))
    if args.dry_run or args.skip_check: return 0
    checker=root/"tools"/"check_release_version.py"
    if checker.is_file():
        r=subprocess.run([sys.executable,str(checker)],cwd=root)
        if r.returncode: return r.returncode
        print("PASS: release identity is synchronized at 6.1.2")
    return 0
if __name__=="__main__": raise SystemExit(main())
