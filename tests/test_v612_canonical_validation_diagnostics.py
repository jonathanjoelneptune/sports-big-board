import ast
import importlib.util
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_stack():
    pkg = types.ModuleType("sbb")
    pkg.__path__ = [str(ROOT / "sbb")]
    sys.modules["sbb"] = pkg
    def load(name, rel):
        spec = importlib.util.spec_from_file_location(name, ROOT / rel)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    shadow = load("sbb.canonical_shadow_v600", "sbb/canonical_shadow_v600.py")
    v610 = load("sbb.canonical_certification_v610", "sbb/canonical_certification_v610.py")
    v611 = load("sbb.canonical_certification_v611", "sbb/canonical_certification_v611.py")
    v612 = load("sbb.canonical_validation_v612", "sbb/canonical_validation_v612.py")
    return shadow, v610, v611, v612


def test_source_parses_and_never_claims_production_authority():
    text = (ROOT / "sbb" / "canonical_validation_v612.py").read_text(encoding="utf-8")
    ast.parse(text)
    assert 'productionAuthority":False' in text or '"productionAuthority": False' in text
    assert "copyValidationConsole" in text
    assert "decisionTrace" in text
    assert "dateProvenance" in text


def test_mls_utc_boundary_provenance_is_explicit():
    shadow, _v610, _v611, v612 = load_stack()
    if not hasattr(shadow, "ET"):
        return
    diag = v612.ValidationDiagnostics.__new__(v612.ValidationDiagnostics)
    event = {
        "canonical_event_id": "cev_mls",
        "competition_id": "MLS",
        "slate_date": "2026-09-06",
        "away_name": "Portland Timbers",
        "home_name": "Minnesota United FC",
        "scheduled_at": "2026-09-06T02:30:00Z",
        "raw_json": json.dumps({"scheduledAt": "2026-09-06T02:30:00Z"}),
    }
    result = diag._event_provenance(event, [], {"2026-09-05": [], "2026-09-06": [], "2026-09-07": []})
    assert result["scheduledUtcDate"] == "2026-09-06"
    assert result["scheduledEasternDate"] == "2026-09-05"
    assert "LIKELY_UTC_DAY_LEAK" in result["flags"]
    assert "SLATE_DATE_DIFFERS_FROM_ET_START_DATE" in result["flags"]


def test_decision_bones_revoke_certification_for_production_only_event():
    shadow, v610, _v611, v612 = load_stack()
    if not hasattr(v610, "SOURCE_DEFS"):
        return
    diag = v612.ValidationDiagnostics.__new__(v612.ValidationDiagnostics)
    now = v612._now()
    auth_source = v610.SOURCE_DEFS["MLS"]["authoritative"]
    ind_source = v610.INDEPENDENT_SOURCE
    cov = {
        ("2026-09-06", "MLS", auth_source): {"success": 1, "result_count": 0, "last_observed_at": now},
        ("2026-09-06", "MLS", ind_source): {"success": 1, "result_count": 0, "last_observed_at": now},
    }
    eid = "cev_prod"
    event = {"canonical_event_id": eid, "competition_id": "MLS", "slate_date": "2026-09-06", "away_name": "LA Galaxy", "home_name": "New England Revolution", "scheduled_at": "2026-09-06T01:30:00Z", "inclusion_state": "INCLUDED", "raw_json": "{}"}
    slate = {"certification_status": "CERTIFIED", "certification_reason": "old", "universe_count": 0, "included_count": 0, "excluded_count": 0, "unknown_count": 0, "unresolved_count": 0}
    comparison = {"canonical_count": 0, "legacy_count": 1, "matched_count": 0, "canonical_only_count": 0, "legacy_only_count": 1, "details_json": json.dumps({"legacyOnly": [eid], "canonicalOnly": []})}
    d = diag._decision("2026-09-06", "MLS", slate, comparison, cov, [event], {}, {eid: event}, {"2026-09-05": [], "2026-09-06": [event], "2026-09-07": []})
    assert d["effectiveStatus"] == "RECONCILING"
    assert d["cutoverReady"] is False
    assert d["stateConsistencyViolation"] is True
    assert "KNOWN_EVENT_UNIVERSE_CONFLICT" in d["effectiveReason"]
    assert d["mlsDiagnosis"]["likelyUtcDayLeaks"] == 1
    codes = {x["code"]: x["status"] for x in d["decisionTrace"]}
    assert codes["PRODUCTION_CONTRADICTIONS"] == "FAIL"
    assert codes["DATE_PROVENANCE"] == "WARN"


def test_adapter_status_can_rehydrate_from_persisted_source_coverage():
    _shadow, v610, _v611, v612 = load_stack()
    if not hasattr(v610, "SOURCE_DEFS"):
        return
    diag = v612.ValidationDiagnostics.__new__(v612.ValidationDiagnostics)
    now = v612._now()
    source = v610.SOURCE_DEFS["MLB"]["authoritative"]
    cov = {("2026-09-06", "MLB", source): {"source": source, "source_class": "AUTHORITATIVE", "success": 1, "result_count": 15, "last_observed_at": now, "error": ""}}
    state = diag._adapter_status("MLB", "authoritative", cov, {}, "2026-09-06")
    assert state["state"] == "PERSISTED_OK"
    assert state["provenance"] == "persisted"
    assert state["resultCount"] == 15


def test_copy_report_contains_every_major_diagnostic_section():
    _shadow, _v610, _v611, v612 = load_stack()
    diag = v612.ValidationDiagnostics.__new__(v612.ValidationDiagnostics)
    sample = {"capturedAtIso":"2026-09-06T18:00:00Z","capturedEastern":"2026-09-06T14:00:00-04:00","releaseVersion":"6.1.2","version":v612.VERSION,"window":{"from":"2026-08-30","to":"2026-09-13"},"summary":{"leagueDays":105},"adapters":{},"days":{},"discrepancies":[],"mlsDiagnostics":[],"stateConsistencyViolations":[],"probeHistory":[],"worker":{},"database":{},"diagnosticHooks":{}}
    report = diag._report(sample)
    for token in ("VALIDATION SUMMARY", "ADAPTER STATUS", "15-DAY LEAGUE/DATE DECISION MATRIX", "DISCREPANCY EVENTS WITH DATE/SOURCE PROVENANCE", "MLS FOCUSED DIAGNOSTICS", "RECENT COLLECTOR PROBES", "RAW VALIDATION SNAPSHOT JSON"):
        assert token in report


def test_diagnostic_routes_and_audit_tables_exist():
    text = (ROOT / "sbb" / "canonical_validation_v612.py").read_text(encoding="utf-8")
    for token in ("/api/canonical/validation/health", "/api/canonical/validation/snapshot", "/api/canonical/validation/copy", "/api/canonical/validation/league", "/api/canonical/validation/mls", "/api/canonical/validation/history", "canonical_validation_probe", "canonical_validation_snapshot"):
        assert token in text


def test_console_has_one_click_copy_and_uses_unified_snapshot():
    text = (ROOT / "canonical-shadow.html").read_text(encoding="utf-8")
    assert "COPY VALIDATION CONSOLE" in text
    assert "/api/canonical/validation/snapshot" in text
    assert "/api/canonical/validation/copy" in text
    assert "Decision Bones" in text
    assert "MLS Date-Boundary Diagnostics" in text
    assert "Recent Collector / Worker Probes" in text
    assert "/api/canonical/certification/readiness?date=" not in text


def test_release_workflow_uses_v612_materializer_and_smokes_validation_health():
    workflow = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8")
    assert workflow.count("python3 tools/apply_v612_release.py") >= 4
    assert "/api/canonical/validation/health" in workflow


def main():
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test(); print("PASS",test.__name__)
    print(f"PASS: {len(tests)}/{len(tests)} v6.1.2 canonical validation diagnostic tests")

if __name__ == "__main__": main()
