#!/usr/bin/env python3
"""Sports Big Board v6.1.5 canonical installer dependency repair."""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path

BASE='6.1.4'
NEW='6.1.5'
TEXT_SUFFIXES={'.py','.js','.css','.html','.json','.sh','.yml','.yaml'}
ACTIVE_DIRS=('ui','architecture','sbb','tests','cloud','.github')


def active_files(root):
    seen=set()
    for p in sorted(root.iterdir()):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:
            seen.add(p); yield p
    checker=root/'tools'/'check_release_version.py'
    if checker.is_file() and checker not in seen:
        seen.add(checker); yield checker
    for dirname in ACTIVE_DIRS:
        base=root/dirname
        if not base.is_dir(): continue
        for p in sorted(base.rglob('*')):
            if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES: continue
            rel=p.relative_to(root)
            if any(part.startswith('sports-big-board-v') for part in rel.parts): continue
            if p not in seen:
                seen.add(p); yield p


def run_base(root):
    (root/'VERSION').write_text(BASE+'\n',encoding='utf-8')
    arch=root/'architecture'/'VERSION'; arch.parent.mkdir(parents=True,exist_ok=True); arch.write_text(BASE+'\n',encoding='utf-8')
    subprocess.run([sys.executable,str(root/'tools'/'apply_v614_release.py'),'--skip-check'],cwd=root,check=True)


def patch_install_chain(root):
    path=root/'sbb'/'__init__.py'
    text=path.read_text(encoding='utf-8')
    v611_call='_install_canonical_certification_v611()'
    v612_call='_install_canonical_validation_v612()'
    if v612_call not in text:
        raise SystemExit('ERROR: canonical validation installer anchor missing after v6.1.4 materialization')
    if v611_call not in text:
        block=(
            '\n# v6.1.5: restore the missing v6.1.1 certification-hardening dependency.\n'
            '# Validation waits on v611.engine(), so hardening must install first.\n'
            'from .canonical_certification_v611 import install as _install_canonical_certification_v611\n'
            '_install_canonical_certification_v611()\n\n'
        )
        anchor='# v6.1.2: unified canonical slate validation diagnostics + copy console.\n'
        if anchor not in text:
            raise SystemExit('ERROR: canonical validation comment anchor missing')
        text=text.replace(anchor,block+anchor,1)
        path.write_text(text,encoding='utf-8')
    text=path.read_text(encoding='utf-8')
    if text.index(v611_call) > text.index(v612_call):
        raise SystemExit('ERROR: canonical certification hardening must install before validation')


def patch_verify(root):
    path=root/'VERIFY.sh'; text=path.read_text(encoding='utf-8')
    cmd='python3 tests/test_v615_canonical_install_chain.py'
    if cmd not in text:
        anchor='python3 tools/check_release_version.py'
        if anchor not in text: raise SystemExit('ERROR: VERIFY release-check anchor missing')
        path.write_text(text.replace(anchor,anchor+'\n'+cmd,1),encoding='utf-8')


def promote(root):
    for p in active_files(root):
        try: source=p.read_text(encoding='utf-8')
        except UnicodeDecodeError: continue
        rendered=source.replace(BASE,NEW)
        if rendered!=source: p.write_text(rendered,encoding='utf-8')
    for p in (root/'VERSION',root/'architecture'/'VERSION'):
        p.parent.mkdir(parents=True,exist_ok=True); p.write_text(NEW+'\n',encoding='utf-8')


def controller(root):
    src=root/f'CONTROLLER-REGION-MAP-v{BASE}.md'; dst=root/f'CONTROLLER-REGION-MAP-v{NEW}.md'
    if not src.is_file(): raise SystemExit(f'ERROR: missing {src.name}')
    dst.write_text(src.read_text(encoding='utf-8').replace(BASE,NEW),encoding='utf-8')


def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument('--dry-run',action='store_true'); ap.add_argument('--skip-check',action='store_true')
    args=ap.parse_args(argv); root=Path(__file__).resolve().parents[1]
    current=(root/'VERSION').read_text(encoding='utf-8').strip()
    if current!=NEW: raise SystemExit(f'ERROR: expected VERSION {NEW}, got {current!r}')
    required=[root/'tools'/'apply_v614_release.py',root/'sbb'/'canonical_certification_v611.py',root/'sbb'/'canonical_validation_v612.py',root/'tests'/'test_v615_canonical_install_chain.py']
    missing=[str(x.relative_to(root)) for x in required if not x.is_file()]
    if missing: raise SystemExit('ERROR: incomplete v6.1.5 release: '+', '.join(missing))
    if args.dry_run:
        print('v6.1.5: preserve v6.1.4 and install canonical certification hardening before validation'); return 0
    run_base(root); patch_install_chain(root); patch_verify(root); promote(root); controller(root)
    print('Sports Big Board v6.1.5 materialized')
    print('Canonical install order: v6.1.1 certification hardening -> v6.1.2 validation diagnostics')
    if args.skip_check: return 0
    subprocess.run([sys.executable,str(root/'tools'/'check_release_version.py')],cwd=root,check=True)
    print('PASS: deployment-critical release identity is synchronized at 6.1.5')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
