from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
MILESTONE=(ROOT/'architecture'/'milestone-console.js').read_text(encoding='utf-8')
CERT=(ROOT/'architecture'/'foundation-certification.js').read_text(encoding='utf-8')
APP=(ROOT/'app.js').read_text(encoding='utf-8')
MANIFEST=(ROOT/'foundation-certification.json').read_text(encoding='utf-8')


def test_release_retains_v434_soak_closure_or_newer():
    assert tuple(map(int, VERSION.split('.'))) >= (4,3,4)


def test_soak_requires_continuous_telemetry_not_wall_clock_only():
    for token in ('expectedSamples','minimumSamples','coverageRatio','sampledSpanMs','maxSampleGapMs','maxAllowedSampleGapMs'):
        assert token in MILESTONE
    assert 'soak telemetry coverage too low' in MILESTONE
    assert 'soak telemetry span too short' in MILESTONE
    assert 'soak telemetry gap' in MILESTONE


def test_soak_detects_stuck_playing_and_buffering():
    assert 'playing without forward progress' in MILESTONE
    assert 'sustained buffering' in MILESTONE
    assert 'maxNoProgressMs' in MILESTONE
    assert 'maxBufferingMs' in MILESTONE


def test_soak_transitions_are_bounded():
    assert 'withTimeout' in MILESTONE
    assert "'soak game transition'" in MILESTONE
    assert 'transitionTimeouts' in MILESTONE
    assert 'transitionWindows' in MILESTONE


def test_tier2_certificate_surfaces_new_soak_gates():
    for token in ('tier2Evaluation','Tier 2 telemetry coverage','Tier 2 continuous observation span','Tier 2 maximum sample gap','Tier 2 playback forward progress','Tier 2 sustained buffering','Tier 2 bounded transitions'):
        assert token in CERT


def test_unattended_decode_or_provider_failure_auto_skips():
    assert 'SKIPPING UNAVAILABLE VIDEO' in APP
    assert 'automatic playback failure recovery' in APP
    assert 'AUTO_MEDIA_FAILURE_SKIP' in APP
    assert "if(!userInitiated)" in APP
    assert "tryScoreMediaFallback(failed,err?.message||'score playback failed')" in APP


def test_manifest_records_soak_limits():
    for token in ('minimumTelemetryCoverageRatio','maximumSampleGapMs','maximumNoProgressMs','maximumBufferingMs','transitionTimeoutMs'):
        assert token in MANIFEST
