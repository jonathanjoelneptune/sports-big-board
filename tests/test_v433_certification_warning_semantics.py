import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CERT=(ROOT/'architecture'/'foundation-certification.js').read_text(encoding='utf-8')
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()


def test_release_retains_v433_warning_semantics_or_newer():
    assert tuple(map(int, VERSION.split('.'))) >= (4,3,3)


def test_tier3_allows_advisory_warn_without_allowing_fail():
    assert "allowWarnings=false" in CERT
    assert "new Set(['PASS','WARN'])" in CERT
    assert "runStatus==='PASS'||(allowWarnings&&runStatus==='WARN')" in CERT
    assert "tierRunEvidence('tier3','Tier 3 chaos',run,0,{allowWarnings:true})" in CERT
    # The strict default is retained for Tier 2 and other callers.
    assert "tierRunEvidence('tier2','Tier 2 soak',run,SOAK_MS-2000)" in CERT


def test_tier3_certificate_surfaces_warnings_instead_of_hiding_them():
    assert "`${id}-warnings`" in CERT
    assert "advisory warnings" in CERT
    assert "warningCount:warnings.length" in CERT
    assert "no failed evidence" in CERT
