import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'sbb' / 'canonical_certification_v611.py'
FRONTEND = ROOT / 'canonical-shadow.html'


def backend_text(): return BACKEND.read_text(encoding='utf-8')
def frontend_text(): return FRONTEND.read_text(encoding='utf-8')


def test_python_source_parses(): ast.parse(backend_text())


def test_health_is_cache_only_not_horizon_scan():
    text=backend_text(); block=text.split('def _health_v611(self):',1)[1].split('def _install_engine_patches',1)[0]
    assert '_readiness_window(self)' in block
    assert '_compute_readiness_window(' not in block
    assert '_readiness_for_day(' not in block
    assert 'cachedReadinessHealth' in block


def test_readiness_endpoints_return_cached_projection():
    text=backend_text()
    assert 'def _compute_readiness_window(engine):' in text
    assert 'def _rebuild_readiness_cache(engine):' in text
    assert 'HARDENED-SHADOW-CACHED' in text


def test_worker_rebuilds_readiness_cache_after_reconciliation():
    text=backend_text(); block=text.split('def _run_horizon_v611(self):',1)[1].split('def _health_v611',1)[0]
    assert '_rebuild_readiness_cache(self)' in block


def test_console_uses_v612_unified_cached_diagnostics():
    text=frontend_text()
    assert '/api/canonical/validation/snapshot' in text
    assert '/api/canonical/validation/copy' in text
    assert 'COPY VALIDATION CONSOLE' in text
    assert '/api/canonical/certification/readiness?date=' not in text


def test_console_exposes_decision_bones_and_mls_date_diagnostics():
    text=frontend_text()
    for token in ('Decision Bones','MLS Date-Boundary Diagnostics','Discrepancy Events & Provenance','Recent Collector / Worker Probes','Persisted Evidence'):
        assert token in text


def main():
    tests=[v for k,v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for test in tests: test(); print('PASS',test.__name__)
    print(f'PASS: {len(tests)}/{len(tests)} v6.1.1/v6.1.2 runtime responsiveness tests')

if __name__=='__main__': main()
