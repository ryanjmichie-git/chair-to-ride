"""CP3: a vehicle_down event replayed against a finished run re-plans the rest of the day.

Definition of done: the re-plan takes <= 30 s, verifies clean, and no rider the down van was
carrying is stranded (H11: scheduled on another van, or in the review queue).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from c2r import ledger, perturb
from c2r.llm import FakeMediator
from c2r.models import TripStatus
from c2r.state import load_state
from c2r.timeutil import to_min

DATA = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "42"
T_DOWN = "13:40"


@pytest.fixture(scope="module")
def replan(fake_run, tmp_path_factory: pytest.TempPathFactory):
    out = tmp_path_factory.mktemp("cp3-fake")
    event = perturb.load_event(DATA, "vehicle_down", T_DOWN)
    result = perturb.run(DATA, fake_run.out, out, event, FakeMediator(), echo=lambda *_: None)
    return out, result, event


def _after(out: Path) -> dict:
    return json.loads((out / "schedule_after.json").read_text(encoding="utf-8"))["manifest"]


def _stops(manifest: dict, before: int | None = None) -> set[tuple]:
    return {
        (r["vehicle_id"], s["trip_id"], s["kind"], s["eta"], s["node"])
        for r in manifest["routes"]
        for s in r["stops"]
        if before is None or to_min(s["eta"]) < before
    }


def test_load_event_finds_the_entry_or_says_what_exists() -> None:
    event = perturb.load_event(DATA, "vehicle_down", T_DOWN)
    assert event.type.value == "vehicle_down" and event.payload["vehicle_id"] == "V3"
    with pytest.raises(ValueError, match="13:40"):
        perturb.load_event(DATA, "vehicle_down", "09:00")


def test_replan_meets_the_definition_of_done(replan) -> None:
    out, result, event = replan
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["elapsed_s"] <= 30
    assert not result.result.violations
    record = json.loads((out / "event.json").read_text(encoding="utf-8"))
    assert record["event"] == event.model_dump(mode="json")
    assert record["now"] == T_DOWN and record["affected"]
    assert next(v for v in record["fleet"] if v["vehicle_id"] == "V3")["status"] == "down"


def test_the_down_van_takes_no_stop_after_t_down(replan) -> None:
    out, _, _ = replan
    late = [s for s in _stops(_after(out)) if s[0] == "V3" and to_min(s[3]) >= to_min(T_DOWN)]
    assert late == []


def test_every_affected_return_is_reassigned_or_queued(replan) -> None:
    out, result, _ = replan
    manifest = _after(out)
    affected = json.loads((out / "event.json").read_text(encoding="utf-8"))["affected"]
    trips = {t["trip_id"]: t for t in manifest["trips"]}
    served = {(s[1], s[2]) for s in _stops(manifest)}
    queued = {item.subject for item in result.review}
    for trip_id in affected:
        trip = trips[trip_id]
        if trip["status"] == TripStatus.scheduled.value:
            assert trip["vehicle_id"] != "V3"
            assert (trip_id, "pickup") in served and (trip_id, "dropoff") in served
        else:
            assert trip_id in queued, f"{trip_id} is {trip['status']} and not in the review queue"


def test_the_past_is_untouched(replan) -> None:
    out, _, _ = replan
    before = json.loads((out / "schedule_before.json").read_text(encoding="utf-8"))["manifest"]
    assert _stops(before, to_min(T_DOWN)) == _stops(_after(out), to_min(T_DOWN))


def test_ledger_replays_from_the_event_state(replan, fake_run) -> None:
    out, _, event = replan
    state, _, _ = perturb.event_state(load_state(DATA), fake_run.out, event)
    replayed = ledger.replay(state, ledger.read(out / "ledger.jsonl"))
    dump = json.dumps(
        {
            "roster": replayed.roster.model_dump(mode="json"),
            "manifest": replayed.manifest.model_dump(mode="json"),
        },
        indent=2,
        sort_keys=True,
    )
    assert dump + "\n" == (out / "schedule_after.json").read_bytes().decode("utf-8")


def test_run_start_records_the_event_and_its_source(replan, fake_run) -> None:
    out, _, _ = replan
    entries = ledger.read(out / "ledger.jsonl")
    start = entries[0].payload
    assert start["event"]["type"] == "vehicle_down" and start["now"] == T_DOWN
    assert start["source_run_id"] == ledger.read(fake_run.out / "ledger.jsonl")[0].run_id
    assert {"source.schedule_after.json", "event"} <= set(entries[0].input_hashes)


def test_the_harness_closes_the_replan_once_the_stop_rule_is_met(replan) -> None:
    """After an apply whose stop block says finish, the harness ends the run itself: one turn
    less on the 30 s clock. The closing pass still queues whatever is left."""
    out, _, _ = replan
    entries = ledger.read(out / "ledger.jsonl")
    assert entries[-1].payload["reason"].startswith("stop rule met")
    assert max(e.iteration for e in entries if e.actor == "model") == 2


def test_event_state_reproduces_the_source_runs_past(fake_run) -> None:
    """Everything the source run had done before `now` is in the event state unchanged."""
    event = perturb.load_event(DATA, "vehicle_down", T_DOWN)
    state, _, affected = perturb.event_state(load_state(DATA), fake_run.out, event)
    source = json.loads((fake_run.out / "schedule_after.json").read_text(encoding="utf-8"))
    now = to_min(T_DOWN)
    assert state.now == now and affected
    assert _stops(state.manifest.model_dump(mode="json"), now) == _stops(source["manifest"], now)
    starts = {p.patient_id: p.start_time for p in state.roster.patients}
    assert starts == {p["patient_id"]: p["start_time"] for p in source["roster"]["patients"]}
