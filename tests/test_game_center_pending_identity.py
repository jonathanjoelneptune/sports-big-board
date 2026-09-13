#!/usr/bin/env python3
"""Regression coverage for Game Center pending-request identity."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "architecture" / "game-center-contract.js"


def _source() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def test_pending_202_keeps_the_original_request_alias():
    """A 202 must poll the same alias so one server preparation job owns the load."""
    source = _source()
    resolved_decl = source.index("const resolvedRequestId=clean(payload?.resolvedEventId);")
    pending_branch = source.index("if(response.status===202||payload?.pending)")
    ready_handoff = source.index("if(resolvedRequestId)requestId=resolvedRequestId;")

    assert resolved_decl < pending_branch < ready_handoff
    pending_body = source[pending_branch:ready_handoff]
    assert "continue;" in pending_body
    assert "requestId=resolvedRequestId" not in pending_body


def test_resolved_provider_id_is_adopted_only_after_a_successful_response():
    """Once preparation is ready, cache/normalization should use the resolved ID."""
    source = _source()
    response_ok = source.index("if(!response.ok)")
    ready_handoff = source.index("if(resolvedRequestId)requestId=resolvedRequestId;")
    payload_use = source.index("const raw=payload?.data||payload;")

    assert response_ok < ready_handoff < payload_use
    assert "stable pending-request identity" in source
