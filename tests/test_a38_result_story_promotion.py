#!/usr/bin/env python3
"""A3.8 result story-promotion + presentation regression coverage."""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "refresh_sports_ticker.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a38", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def result_candidate(*, cid="cand-mets", title="New York Mets beat San Francisco Giants 10-6", fused=None):
    return {
        "candidateId": cid,
        "leagueHint": "MLB",
        "sportHint": "baseball",
        "typeHint": "RESULT",
        "title": title,
        "summary": "Highlightly final: San Francisco Giants 6, New York Mets 10.",
        "occurredAt": "2026-09-04T23:10:00Z",
        "timePrecision": "exact",
        "ageHours": 3.4,
        "quality": 100,
        "sourceRecords": [
            {"sourceId": "highlightly-baseball-2026-09-04", "provider": "Highlightly", "url": "https://highlightly.net", "rawRef": "x"},
        ],
        "metadata": {
            "matchId": 12345,
            "homeTeam": "New York Mets",
            "awayTeam": "San Francisco Giants",
            "homeScore": 10,
            "awayScore": 6,
            "fusedContext": list(fused or []),
        },
    }


def test_multi_homer_recap_becomes_story_promotion():
    candidate = result_candidate(fused=[{
        "candidateId": "cand-espn-mets",
        "providers": ["ESPN"],
        "title": "Alvarez hits 2 homers and Mets go deep 5 times to back McLean in 10-6 win over Giants",
        "summary": "Francisco Alvarez hit two of New York's five home runs, leading the Mets to a 10-6 win over the Giants.",
    }])
    promotion = mod.build_result_story_promotion(candidate)
    assert promotion, candidate
    assert "MULTI_HOMER" in promotion["signals"], promotion
    assert promotion["priorityFloor"] >= 74, promotion
    assert "Alvarez" in promotion["headlineSeed"], promotion


def test_generic_score_headline_and_raw_highlightly_text_are_promoted():
    candidate = result_candidate(fused=[{
        "candidateId": "cand-espn-mets",
        "providers": ["ESPN"],
        "title": "Alvarez hits 2 homers and Mets go deep 5 times to back McLean in 10-6 win over Giants",
        "summary": "Francisco Alvarez hit two of New York's five home runs Friday night, leading the Mets to a 10-6 win.",
    }])
    log = mod.initial_run_log(mod.parse_datetime("2026-09-05T02:36:03Z"), mod.parse_datetime("2026-09-04T02:36:03Z"), "gpt-4o-mini")
    mod.promote_result_story_context([candidate], log)
    by_id = {candidate["candidateId"]: candidate}
    item = {
        "type": "RESULT",
        "priority": 65,
        "headline": "New York Mets beat San Francisco Giants 10-6",
        "text": "Highlightly final: San Francisco Giants 6, New York Mets 10.",
        "freshnessBasis": "Francisco Alvarez hit two home runs, fueling the Mets' win.",
    }
    mod.repair_result_story_punch(item, [candidate["candidateId"]], by_id, "MLB #1", log)
    assert "Alvarez" in item["headline"], item
    assert "2 homers" in item["headline"] or "two" in item["headline"].lower(), item
    assert not item["text"].lower().startswith("highlightly final:"), item
    assert "Alvarez" in item["text"], item


def test_contextual_headline_kept_but_raw_text_still_replaced():
    candidate = result_candidate(fused=[{
        "candidateId": "cand-espn-mets",
        "providers": ["ESPN"],
        "title": "Alvarez hits 2 homers and Mets go deep 5 times to back McLean in 10-6 win over Giants",
        "summary": "Francisco Alvarez hit two of New York's five home runs Friday night.",
    }])
    log = mod.initial_run_log(mod.parse_datetime("2026-09-05T02:36:03Z"), mod.parse_datetime("2026-09-04T02:36:03Z"), "gpt-4o-mini")
    mod.promote_result_story_context([candidate], log)
    item = {
        "type": "RESULT",
        "priority": 74,
        "headline": "Francisco Alvarez homers twice as Mets beat Giants 10-6",
        "text": "Highlightly final: San Francisco Giants 6, New York Mets 10.",
        "freshnessBasis": "Alvarez homered twice.",
    }
    original_headline = item["headline"]
    mod.repair_result_story_punch(item, [candidate["candidateId"]], {candidate["candidateId"]: candidate}, "MLB #1", log)
    assert item["headline"] == original_headline, item
    assert not item["text"].lower().startswith("highlightly final:"), item


def test_two_run_homer_context_can_outrank_plain_result():
    candidate = result_candidate(
        cid="cand-white-sox",
        title="Chicago White Sox beat Minnesota Twins 4-1",
        fused=[{
            "candidateId": "cand-espn-white-sox",
            "providers": ["ESPN"],
            "title": "Montgomery hits two-run homer as White Sox beat Twins 4-1",
            "summary": "Colson Montgomery hit a two-run homer as Chicago beat Minnesota 4-1.",
        }],
    )
    candidate["metadata"].update({
        "homeTeam": "Chicago White Sox", "awayTeam": "Minnesota Twins", "homeScore": 4, "awayScore": 1,
    })
    log = mod.initial_run_log(mod.parse_datetime("2026-09-05T02:36:03Z"), mod.parse_datetime("2026-09-04T02:36:03Z"), "gpt-4o-mini")
    mod.promote_result_story_context([candidate], log)
    priority = mod.apply_result_enrichment_priority(
        65, [candidate["candidateId"]], {candidate["candidateId"]: candidate}, "RESULT", "MLB #3", log
    )
    assert priority >= 69, priority


def test_close_score_alone_does_not_receive_story_promotion():
    candidate = result_candidate(
        cid="cand-redsox",
        title="Boston Red Sox beat Baltimore Orioles 1-0",
        fused=[],
    )
    candidate["metadata"].update({
        "homeTeam": "Baltimore Orioles", "awayTeam": "Boston Red Sox", "homeScore": 0, "awayScore": 1,
    })
    promotion = mod.build_result_story_promotion(candidate)
    assert promotion is None, promotion
    enrichment = mod.derive_decisive_context(candidate, {}, [])
    assert enrichment["priorityFloor"] == 63, enrichment
    log = mod.initial_run_log(mod.parse_datetime("2026-09-05T02:36:03Z"), mod.parse_datetime("2026-09-04T02:36:03Z"), "gpt-4o-mini")
    candidate["metadata"]["resultEnrichment"] = enrichment
    base = mod.normalize_editor_priority(100, "RESULT", "MLB #1", log)
    final = mod.apply_result_enrichment_priority(base, [candidate["candidateId"]], {candidate["candidateId"]: candidate}, "RESULT", "MLB #1", log)
    assert base == 65
    assert final == 65


def test_serena_venus_us_open_loss_is_result():
    kind = mod.keyword_type_hint(
        "Serena, Venus Williams lose 3rd-set tiebreak in US Open return",
        "Serena and Venus Williams are out of the US Open women's doubles after losing in a third-set tiebreaker.",
    )
    assert kind == "RESULT", kind


def test_atomic_write_persists_nonempty_log_payload():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sports-ticker-run-log.json"
        mod.atomic_write(path, '{"status":"success"}\n')
        assert path.exists()
        assert path.stat().st_size > 0
        assert path.read_text() == '{"status":"success"}\n'



def test_strong_promoted_story_is_auto_added_when_editor_omits_it():
    candidate = result_candidate(fused=[{
        "candidateId": "cand-espn-mets",
        "providers": ["ESPN"],
        "title": "Alvarez hits 2 homers and Mets go deep 5 times to back McLean in 10-6 win over Giants",
        "summary": "Francisco Alvarez hit two of New York's five home runs Friday night, leading the Mets to a 10-6 win.",
    }])
    log = mod.initial_run_log(mod.parse_datetime("2026-09-05T02:36:03Z"), mod.parse_datetime("2026-09-04T02:36:03Z"), "gpt-4o-mini")
    mod.promote_result_story_context([candidate], log)
    by_id = {candidate["candidateId"]: candidate}
    final_items = []
    final_items = mod.ensure_promoted_result_coverage(final_items, "MLB", [candidate], by_id, log)
    assert len(final_items) == 1, final_items
    assert "Alvarez" in final_items[0]["headline"], final_items
    assert final_items[0]["priority"] >= 74, final_items
    assert log["pipeline"]["resultStoryPromotion"]["autoAdded"], log


def test_decisive_walkoff_outranks_generic_close_result():
    close = result_candidate(cid="cand-close", title="Boston Red Sox beat Baltimore Orioles 1-0", fused=[])
    close["metadata"].update({"homeTeam":"Baltimore Orioles","awayTeam":"Boston Red Sox","homeScore":0,"awayScore":1})
    close_enrichment = mod.derive_decisive_context(close, {}, [])
    close["metadata"]["resultEnrichment"] = close_enrichment

    walkoff = result_candidate(cid="cand-walkoff", title="Cleveland Guardians beat Detroit Tigers 7-6", fused=[])
    walkoff["metadata"].update({"homeTeam":"Cleveland Guardians","awayTeam":"Detroit Tigers","homeScore":7,"awayScore":6})
    walkoff["metadata"]["resultEnrichment"] = {
        "flags":["WALK_OFF","GAME_WINNER","ONE_RUN_GAME"],
        "decisiveMoment":"Brayan Rocchio delivered the walk-off in the bottom of the 9th inning.",
        "headlineSeed":"Brayan Rocchio delivers walk-off as Cleveland Guardians beat Detroit Tigers 7-6",
        "summarySeed":"Rocchio homered to left center (405 feet).",
        "priorityFloor":78,
    }
    log = mod.initial_run_log(mod.parse_datetime("2026-09-05T02:36:03Z"), mod.parse_datetime("2026-09-04T02:36:03Z"), "gpt-4o-mini")
    mod.promote_result_story_context([close, walkoff], log)
    assert close["metadata"].get("storyPromotion") is None
    assert walkoff["metadata"]["storyPromotion"]["kind"] == "decisive-moment"
    auto = mod.ensure_promoted_result_coverage([], "MLB", [close, walkoff], {close["candidateId"]:close, walkoff["candidateId"]:walkoff}, log)
    assert len(auto) == 1
    assert "walk-off" in auto[0]["headline"].lower()
    assert auto[0]["priority"] == 78

def test_raw_highlightly_text_never_survives_without_story_context():
    candidate = result_candidate(
        cid="cand-redsox-natural",
        title="Boston Red Sox beat Baltimore Orioles 1-0",
        fused=[],
    )
    candidate["metadata"].update({
        "homeTeam":"Baltimore Orioles", "awayTeam":"Boston Red Sox",
        "homeScore":0, "awayScore":1,
    })
    log = mod.initial_run_log(mod.parse_datetime("2026-09-05T02:36:03Z"), mod.parse_datetime("2026-09-04T02:36:03Z"), "gpt-4o-mini")
    item = {
        "type":"RESULT", "priority":65,
        "headline":"Boston Red Sox beat Baltimore Orioles 1-0",
        "text":"Highlightly final: Boston Red Sox 1, Baltimore Orioles 0.",
        "freshnessBasis":"The Red Sox edged the Orioles.",
    }
    mod.repair_result_story_punch(item, [candidate["candidateId"]], {candidate["candidateId"]:candidate}, "MLB #1", log)
    assert item["text"] == "Boston Red Sox beat Baltimore Orioles 1-0.", item


def test_liverpool_recap_prefix_is_cleaned_and_promoted():
    candidate = {
        "candidateId":"cand-liverpool", "leagueHint":"EPL", "sportHint":"soccer",
        "typeHint":"RESULT", "title":"Liverpool beat Ipswich 2-0",
        "metadata":{"fusedContext":[{
            "candidateId":"cand-espn-liverpool", "providers":["ESPN"],
            "title":"Premier League recap: Isak's brace vs. Ipswich gives Liverpool first win of the season",
            "summary":"Liverpool defeated Ipswich Town 2-0 for their first win of the Premier League season.",
        }]},
    }
    promotion = mod.build_result_story_promotion(candidate)
    assert promotion["priorityFloor"] >= 72, promotion
    assert promotion["headlineSeed"].startswith("Isak's brace"), promotion
    assert not promotion["headlineSeed"].lower().startswith("premier league recap"), promotion

if __name__ == "__main__":
    test_multi_homer_recap_becomes_story_promotion()
    test_generic_score_headline_and_raw_highlightly_text_are_promoted()
    test_contextual_headline_kept_but_raw_text_still_replaced()
    test_two_run_homer_context_can_outrank_plain_result()
    test_close_score_alone_does_not_receive_story_promotion()
    test_serena_venus_us_open_loss_is_result()
    test_atomic_write_persists_nonempty_log_payload()
    test_raw_highlightly_text_never_survives_without_story_context()
    test_liverpool_recap_prefix_is_cleaned_and_promoted()
    test_strong_promoted_story_is_auto_added_when_editor_omits_it()
    test_decisive_walkoff_outranks_generic_close_result()
    print("PASS: A3.8 result story-promotion regressions")

