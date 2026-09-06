import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'sbb' / 'canonical_certification_v611.py'
FRONTEND = ROOT / 'canonical-shadow.html'


def backend_text():
    return BACKEND.read_text(encoding='utf-8')


def frontend_text():
    return FRONTEND.read_text(encoding='utf-8')


def test_python_source_parses():
    ast.parse(backend_text())


def test_health_is_cache_only_not_horizon_scan():
    text = backend_text()
    block = text.split('def _health_v611(self):', 1)[1].split('def _install_engine_patches', 1)[0]
    assert '_readiness_window(self)' in block
    assert '_compute_readiness_window(' not in block
    assert '_readiness_for_day(' not in block
    assert 'cachedReadinessHealth' in block


def test_readiness_endpoints_return_cached_projection():
    text = backend_text()
    assert 'def _compute_readiness_window(engine):' in text
    assert 'def _rebuild_readiness_cache(engine):' in text
    assert 'def _readiness_window(engine):' in text
    assert 'HARDENED-SHADOW-CACHED' in text
    endpoint = text.split('if parsed.path == "/api/canonical/certification/readiness":', 1)[1]
    endpoint = endpoint.split('return old_get(self)', 1)[0]
    assert '_readiness_for_day(_ENGINE' not in endpoint
    assert '_readiness_window(_ENGINE)' in endpoint


def test_worker_rebuilds_readiness_cache_after_reconciliation():
    text = backend_text()
    block = text.split('def _run_horizon_v611(self):', 1)[1].split('def _health_v611', 1)[0]
    assert '_rebuild_readiness_cache(self)' in block
    initial = text.split('def initial_reconcile():', 1)[1].split('threading.Thread(target=initial_reconcile', 1)[0]
    assert '_rebuild_readiness_cache(_ENGINE)' in initial


def test_console_fails_open_when_certification_diagnostics_are_slow():
    text = frontend_text()
    assert 'AbortController' in text
    assert "json('/api/canonical/certification/health',3000)" in text
    assert "json('/api/canonical/certification/readiness-window',4000)" in text
    assert "/api/canonical/certification/readiness?date=" not in text
    assert 'async function loadDays(days,limit=4)' in text
    assert 'Certification diagnostics unavailable — canonical slate data remains live' in text


def test_console_loads_slate_and_comparison_without_cert_health():
    text = frontend_text()
    load_day = text.split('async function loadDay(day)', 1)[1].split('function map(', 1)[0]
    assert '/api/canonical/slate?date=' in load_day
    assert '/api/canonical/compare?date=' in load_day
    assert '/api/canonical/certification/' not in load_day
    refresh = text.split('async function refresh()', 1)[1].split("$('refresh').onclick", 1)[0]
    assert 'await loadDays(days,4)' in refresh
    assert "certHealth=null;notes.push('cert health unavailable')" in refresh


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    for test in tests:
        test()
        print('PASS', test.__name__)
    print(f'PASS: {len(tests)}/{len(tests)} v6.1.1 runtime responsiveness tests')


if __name__ == '__main__':
    main()
