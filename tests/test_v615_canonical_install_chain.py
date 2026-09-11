#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
assert (ROOT/'VERSION').read_text(encoding='utf-8').strip()=='6.1.5'

init=(ROOT/'sbb'/'__init__.py').read_text(encoding='utf-8')
v611='_install_canonical_certification_v611()'
v612='_install_canonical_validation_v612()'
assert v611 in init,'v6.1.1 certification hardening installer is missing from sbb/__init__.py'
assert v612 in init,'v6.1.2 validation installer is missing from sbb/__init__.py'
assert init.index(v611) < init.index(v612),'validation must install after certification hardening'

hardening=(ROOT/'sbb'/'canonical_certification_v611.py').read_text(encoding='utf-8')
validation=(ROOT/'sbb'/'canonical_validation_v612.py').read_text(encoding='utf-8')
assert 'def engine()' in hardening and 'return _ENGINE' in hardening
assert 'threading.Thread(target=_install_into_server' in hardening
assert 'engine=v611.engine()' in validation
assert 'while True:' in validation
assert '/api/canonical/validation/health' in validation

verify=(ROOT/'VERIFY.sh').read_text(encoding='utf-8')
assert 'tests/test_v615_canonical_install_chain.py' in verify
print('PASS: canonical hardening installs before validation and exposes its engine dependency')
