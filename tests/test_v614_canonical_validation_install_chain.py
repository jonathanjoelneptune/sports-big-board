#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
init_text = (ROOT / "sbb" / "__init__.py").read_text(encoding="utf-8")
workflow = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8")
v612 = (ROOT / "sbb" / "canonical_validation_v612.py").read_text(encoding="utf-8")

v610_call = "_install_canonical_certification_v610()"
v611_call = "_install_canonical_certification_v611()"
v612_call = "_install_canonical_validation_v612()"

for token in (v610_call, v611_call, v612_call):
    assert token in init_text, f"missing canonical install call: {token}"
assert init_text.index(v610_call) < init_text.index(v611_call) < init_text.index(v612_call), "canonical install order must be v610 -> v611 -> v612"
assert "engine=v611.engine()" in v612.replace(" ", ""), "validation diagnostics must wait on v6.1.1 hardening engine"
assert "/api/canonical/validation/health" in workflow, "production smoke must retain validation health gate"
print("PASS v6.1.4 canonical validation install chain")
