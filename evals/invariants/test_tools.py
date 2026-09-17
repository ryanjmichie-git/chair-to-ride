"""The mediator's tools: strict schemas, apply guards, chained bundles, K4 claims, the ledger."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import pytest

from c2r import ledger, tools
from c2r.claims import MAX_MESSAGE_TOKENS, estimate_tokens, numbers_in, numeric_claims
from c2r.models import Usage
from c2r.solver import Result, finish_run
from c2r.state import State, load_rules, load_state
from c2r.verify import schedule_hash

DATA = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "42"
FLAG = {
    "subject": "P30f",
    "reason_code": "STRETCHER",
    "what_was_tried": [],
    "recommended_action": "book a stretcher crew by hand",
    "draft_message": "please book a stretcher crew for the return",
    "owner": "dispatcher",
    "urgency": "today",
}


@dataclass
class Scripted:
    session: tools.Session
    generated: dict
    verified: dict
    applied: dict
    run: Result
    model_applied: int


@pytest.fixture(scope="module")
def baseline() -> State:
    return load_state(DATA)


def propose_verify(session: tools.Session, bid: str) -> dict:
    tools.dispatch(session, "propose_to_unit", {"bundle_id": bid})
    tools.dispatch(session, "propose_to_broker", {"bundle_id": bid})
    return tools.dispatch(session, "verify", {"bundle_id": bid})


@pytest.fixture(scope="module")
def scripted(baseline: State) -> Scripted:
    """One full protocol round the way the fake mediator plays it, then the closing pass."""
    session = tools.new_session(baseline)
    generated = tools.dispatch(session, "generate_candidates", {"side": "both", "k": 6})
    bid = generated["candidates"][0]["bundle_id"]
    verified = propose_verify(session, bid)
    applied = tools.dispatch(
        session,
        "apply_bundle",
        {"bundle_id": bid, "verify_hash": verified["verify_hash"], "rationale": "lowest J"},
    )
    assert applied["applied"], applied
    tools.dispatch(session, "flag_for_review", FLAG)
    tools.dispatch(session, "finish", {"summary": "done"})
    run = finish_run(
        baseline, session.state, session.plan, session.run, session.rejected, session.flagged
    )
    return Scripted(session, generated, verified, applied, run, 1)


def test_eight_strict_tools() -> None:
    names = [t["name"] for t in tools.TOOLS]
    assert names == [
        "get_state",
        "generate_candidates",
        "propose_to_unit",
        "propose_to_broker",
        "verify",
        "apply_bundle",
        "flag_for_review",
        "finish",
    ]
    for tool in tools.TOOLS:
        schema = tool["input_schema"]
        assert tool["strict"] is True
        assert schema["additionalProperties"] is False
        assert schema["required"] == list(schema["properties"])


def test_numeric_claims_skip_identifiers() -> None:
    text = "P31f waits 27 min after 20:35; J 137.3 vs 297.35. S12-B194 on V2 at 2% gets $0.42."
    assert numeric_claims(text) == ["20:35", "27", "137.3", "297.35", "2", "0.42"]
    assert numeric_claims("bundle I03-C001 for R07 on C12") == []


def test_numbers_in_offers_rounded_forms() -> None:
    known = numbers_in({"j": 137.3, "when": "ready at 20:35", "waits": [3, -12.0], "ok": True})
    assert {"137.3", "137", "20:35", "3", "12", "-12"} <= known
    assert "True" not in known


def test_apply_refuses_without_verify_and_both_acceptances(baseline: State) -> None:
    session = tools.new_session(baseline)
    generated = tools.dispatch(session, "generate_candidates", {"side": "both", "k": 3})
    bid = generated["candidates"][0]["bundle_id"]
    bogus = tools.dispatch(session, "apply_bundle", {"bundle_id": bid, "verify_hash": "sha256:0"})
    assert not bogus["applied"] and "call verify first" in bogus["reason"]
    verified = tools.dispatch(session, "verify", {"bundle_id": bid})
    args = {"bundle_id": bid, "verify_hash": verified["verify_hash"], "rationale": ""}
    refused = tools.dispatch(session, "apply_bundle", args)
    assert not refused["applied"] and "broker, unit did not accept" in refused["reason"]
    tools.dispatch(session, "propose_to_unit", {"bundle_id": bid})
    refused = tools.dispatch(session, "apply_bundle", args)
    assert not refused["applied"] and refused["reason"].startswith("broker did not accept")
    unknown = tools.dispatch(session, "apply_bundle", {**args, "bundle_id": "nope"})
    assert not unknown["applied"] and "unknown bundle_id" in unknown["reason"]


def test_apply_refuses_a_hash_from_an_earlier_version(scripted: Scripted) -> None:
    session = scripted.session
    stale = scripted.verified["verify_hash"]
    bid = scripted.applied["next_candidates"][0]["bundle_id"]
    propose_verify(session, bid)
    refused = tools.dispatch(
        session, "apply_bundle", {"bundle_id": bid, "verify_hash": stale, "rationale": ""}
    )
    assert not refused["applied"] and "schedule version 1" in refused["reason"]


def test_autonomy_zero_never_applies() -> None:
    rules = copy.deepcopy(load_rules())
    rules["autonomy_level"] = 0
    session = tools.new_session(load_state(DATA, rules))
    generated = tools.dispatch(session, "generate_candidates", {"side": "broker", "k": 2})
    bid = generated["candidates"][0]["bundle_id"]
    verified = propose_verify(session, bid)
    refused = tools.dispatch(
        session,
        "apply_bundle",
        {"bundle_id": bid, "verify_hash": verified["verify_hash"], "rationale": ""},
    )
    assert not refused["applied"] and "autonomy level 0" in refused["reason"]
    assert session.version == 0 and not session.run.applied


def test_chained_bundle_is_the_best_candidate_and_reproduces(scripted: Scripted) -> None:
    first = scripted.generated["candidates"][0]
    assert first["bundle_id"].endswith("C001")
    assert 1 < len(first["moves"]) <= scripted.session.baseline.rules["max_moves_per_bundle"]
    assert first["j_after"] < scripted.generated["candidates"][1]["j_after"]
    assert scripted.applied["schedule_version"] == 1
    assert scripted.verified["verify_hash"] == scripted.applied["verify_hash"]


def test_tool_results_fit_the_message_budget(scripted: Scripted) -> None:
    assert estimate_tokens(scripted.generated) <= MAX_MESSAGE_TOKENS
    assert estimate_tokens(scripted.applied) <= MAX_MESSAGE_TOKENS
    assert estimate_tokens(tools.dispatch(scripted.session, "get_state", {})) <= 1500


def test_apply_returns_a_delta_not_a_manifest(scripted: Scripted) -> None:
    delta = scripted.applied["delta"]
    assert delta["trips"]
    for change in delta["trips"].values():
        assert set(change) & {"vehicle", "window", "status", "pickup"}
    assert "routes" not in scripted.applied and "manifest" not in scripted.applied


def test_flag_for_review_validates_the_subject(baseline: State) -> None:
    session = tools.new_session(baseline)
    assert not tools.dispatch(session, "flag_for_review", {**FLAG, "subject": "P99"})["queued"]
    queued = tools.dispatch(session, "flag_for_review", FLAG)
    assert queued["queued"] and queued["item_id"] == "M01"
    assert session.flagged[0].draft_message.startswith("SYNTHETIC: ")


def test_finish_run_merges_flagged_items_with_the_computed_queue(scripted: Scripted) -> None:
    review = scripted.run.review
    assert review[0].subject == "P30f" and review[0].reason_code.value == "STRETCHER"
    assert [item.item_id for item in review] == [f"R{n + 1:02d}" for n in range(len(review))]
    assert len({item.subject for item in review}) == len(review)
    assert not scripted.run.result.violations


def test_ledger_roundtrip_replays_to_the_after_schedule(
    tmp_path: Path, baseline: State, scripted: Scripted
) -> None:
    book = ledger.Ledger(
        tmp_path / "ledger.jsonl", "r1", "abc123", "fake-mediator", "none", {"mediator": 1}, {}
    )
    book.start({"seed": 42})
    book.tool(0, "generate_candidates", {"side": "both", "k": 6}, scripted.generated)
    turn_usage = Usage(input=3000, cache_read=0, cache_write=25000, output=200)
    book.model_turn(1, "J is 1117.15", [], ["1117.15"], [], turn_usage, 0.35, "tool_use")
    book.tool(1, "verify", {"bundle_id": "x"}, scripted.verified)
    book.model_turn(
        2, "apply", [], [], [], Usage(input=1500, cache_read=25000, cache_write=1500, output=100), 0.02, "tool_use"
    )
    book.tool(2, "apply_bundle", {"bundle_id": "x"}, scripted.applied)
    closing = [a["bundle"] for a in scripted.run.applied[scripted.model_applied :]]
    book.finish(3, {"closing_bundles": closing, "summary": "done"})
    entries = ledger.read(tmp_path / "ledger.jsonl")
    assert [e.event for e in entries][:3] == ["run_start", "generate_candidates", "model_turn"]
    assert len(ledger.applied_bundles(entries)) == len(scripted.run.applied)
    replayed = ledger.replay(baseline, entries)
    assert schedule_hash(replayed) == schedule_hash(scripted.run.state)
    summary = ledger.usage_summary(entries)
    assert summary["iterations"] == 2 and summary["bundles_applied"] == 1
    assert summary["cost_usd"] == 0.37
    assert summary["cache_read_share_by_iteration"] == {"1": 0.0, "2": 0.8929}
