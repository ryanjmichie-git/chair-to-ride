"""CP3 explanations: Python builds the facts card from the run's files; the writer only phrases it.

I16: every number in an explanation appears in the entries its ``ledger_refs`` point at.
K6: no rider explanation while the rider sits in the review queue.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from c2r import explain, ledger
from c2r.llm import FAKE_MODEL, FakeWriter
from c2r.models import Explanation


@pytest.fixture(scope="module")
def records(fake_run) -> list[dict]:
    return explain.explain_run(fake_run.out, FakeWriter(), echo=lambda *_: None)


def _run_files(out: Path) -> tuple[dict, dict, list, list]:
    before = json.loads((out / "schedule_before.json").read_text(encoding="utf-8"))
    after = json.loads((out / "schedule_after.json").read_text(encoding="utf-8"))
    bundles = json.loads((out / "bundles.json").read_text(encoding="utf-8"))
    queue = json.loads((out / "review_queue.json").read_text(encoding="utf-8"))
    return before, after, bundles, queue


def test_every_record_validates_and_ids_are_unique(records: list[dict]) -> None:
    assert records
    ids = [r["explanation_id"] for r in records]
    assert len(ids) == len(set(ids))
    for record in records:
        explanation = Explanation.model_validate(record["explanation"])
        assert explanation.subject_id == record["facts"]["subject_id"]
        assert explanation.ledger_refs == list(record["facts"]["refs"])
        assert (
            record["explanation_id"]
            == f"E{explanation.subject_id[1:]}{explanation.audience.value[0]}"
        )


def test_every_touched_rider_gets_a_note_unless_queued(records: list[dict], fake_run) -> None:
    _, _, bundles, queue = _run_files(fake_run.out)
    touched = {pid for b in bundles for pid in b["bundle"]["touches"]}
    queued = {explain.patient_of_subject(item["subject"]) for item in queue}
    riders = {r["facts"]["subject_id"] for r in records if r["explanation"]["audience"] == "rider"}
    assert riders == touched - queued
    assert queued, "the fake run should leave the stretcher rider in the queue"
    assert not (riders & queued)


def test_chair_changes_get_a_nurse_note_and_queue_items_a_dispatcher_note(
    records: list[dict], fake_run
) -> None:
    before, after, _, queue = _run_files(fake_run.out)
    starts = {p["patient_id"]: p["start_time"] for p in before["roster"]["patients"]}
    moved = {
        p["patient_id"]
        for p in after["roster"]["patients"]
        if p["start_time"] != starts[p["patient_id"]]
    }
    nurses = {r["facts"]["subject_id"] for r in records if r["explanation"]["audience"] == "nurse"}
    assert nurses == moved
    dispatch = {
        r["facts"]["subject_id"] for r in records if r["explanation"]["audience"] == "dispatcher"
    }
    assert dispatch == {explain.patient_of_subject(item["subject"]) for item in queue}


def test_numbers_come_from_the_refs(records: list[dict]) -> None:
    for record in records:
        assert explain.check_numbers(record) == [], record["explanation_id"]
    tampered = json.loads(json.dumps(records[0]))
    tampered["explanation"]["what_changed"] += " Allow 4321 minutes."
    assert explain.check_numbers(tampered) == ["4321"]


def test_both_new_times_appear_in_the_prose(records: list[dict]) -> None:
    for record in records:
        assert explain.missing_times(record) == [], record["explanation_id"]


def test_reading_grade_is_computed_and_plain(records: list[dict]) -> None:
    for record in records:
        grade = record["explanation"]["reading_grade"]
        assert isinstance(grade, float) and grade <= 8.0, (record["explanation_id"], grade)


def test_refs_resolve_to_run_files(fake_run) -> None:
    refs = explain.resolve_refs(fake_run.out, ["L-1", "S-P30", "S-P30f", "B-P30f"])
    assert refs["L-1"]["event"] == "run_start"
    assert refs["S-P30"]["patient_id"] == "P30" and refs["S-P30f"]["trip_id"] == "P30f"
    assert refs["B-P30f"]["status"] in ("queued", "scheduled", "will_call")
    with pytest.raises(KeyError):
        explain.resolve_refs(fake_run.out, ["S-P99"])


def test_explain_ledger_records_every_call(records: list[dict], fake_run) -> None:
    entries = ledger.read(fake_run.out / "explain.jsonl")
    turns = [e for e in entries if e.actor == "model"]
    assert len(turns) == len(records)
    assert all(e.model_id == FAKE_MODEL and e.prompt_versions == {"explainer": 1} for e in turns)
    assert all(e.payload["unverified"] == [] for e in turns)
    written = json.loads((fake_run.out / "explanations.json").read_text(encoding="utf-8"))
    assert [r["explanation_id"] for r in written] == [r["explanation_id"] for r in records]
