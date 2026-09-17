"""CP3 judge: the model scores six dimensions 0-2; Python overrides what it can prove.

An invented number (I16) zeroes accuracy; a reading grade over 8 caps plain at 1; pass means
total >= 10 and accuracy 2 (handoff 9.C). Scores are written with the ``pass`` key intact.
"""

from __future__ import annotations

import copy
import json

import pytest

from c2r import explain, judge, ledger
from c2r.llm import FAKE_MODEL, FakeJudge, FakeWriter
from c2r.models import Explanation, JudgeScore

DIMENSIONS = ("accuracy", "actionable", "plain", "tone", "complete", "safe")


@pytest.fixture(scope="module")
def records(fake_run) -> list[dict]:
    return explain.explain_run(fake_run.out, FakeWriter(), echo=lambda *_: None)


@pytest.fixture(scope="module")
def scores(records: list[dict], fake_run) -> list[JudgeScore]:
    del records
    return judge.judge_run(fake_run.out, FakeJudge(), echo=lambda *_: None)


def _raw(explanation_id: str, **dims: int) -> dict:
    scores = {d: 2 for d in DIMENSIONS} | dims
    return {"explanation_id": explanation_id, "rationale": "raw", "scores": scores, "pass": True}


def test_scores_are_written_with_the_pass_key(scores: list[JudgeScore], fake_run) -> None:
    written = json.loads((fake_run.out / "judge_scores.json").read_text(encoding="utf-8"))
    assert written and len(written) == len(scores)
    for item in written:
        assert "pass" in item and "pass_" not in item
        JudgeScore.model_validate(item)
    assert all(s.pass_ for s in scores), "fake prose with sourced numbers passes the overrides"


def test_an_invented_number_zeroes_accuracy_and_fails(records: list[dict]) -> None:
    record = copy.deepcopy(records[0])
    record["explanation"]["what_changed"] += " Allow 4321 minutes."
    score = judge.override(record, _raw(record["explanation_id"]))
    assert score.scores.accuracy == 0 and score.pass_ is False
    assert "4321" in score.rationale


def test_pass_needs_total_ten_and_accuracy_two(records: list[dict]) -> None:
    record = records[0]
    eid = record["explanation_id"]
    assert judge.override(record, _raw(eid)).pass_ is True
    assert judge.override(record, _raw(eid, accuracy=1)).pass_ is False  # total 11, accuracy 1
    assert judge.override(record, _raw(eid, tone=0, safe=1)).pass_ is False  # total 9
    assert judge.override(record, _raw(eid, tone=1, safe=1)).pass_ is True  # total 10
    lying = _raw(eid, tone=0, safe=0) | {"pass": True}
    assert judge.override(record, lying).pass_ is False, "the model's own pass flag is not trusted"


def test_a_high_reading_grade_caps_plain(records: list[dict]) -> None:
    record = copy.deepcopy(records[0])
    record["explanation"]["reading_grade"] = 9.4
    score = judge.override(record, _raw(record["explanation_id"]))
    assert score.scores.plain == 1


def test_a_refusal_or_bad_json_is_scored_as_needs_human_edit(records: list[dict]) -> None:
    score = judge.unscored(records[0], "refusal")
    assert score.pass_ is False and score.scores.accuracy == 0
    assert "refusal" in score.rationale


def test_golden_set_is_twelve_items_and_the_provable_buckets_agree() -> None:
    items = judge.load_golden()
    assert len(items) == 12
    assert sum(1 for i in items if i["expected"]["pass"]) == 7
    buckets = [i["expected"]["bucket"] for i in items if not i["expected"]["pass"]]
    assert sorted(buckets) == sorted(["accuracy", "plain", "tone", "complete", "safe"])
    for item in items:
        Explanation.model_validate(item["record"]["explanation"])
        assert item["record"]["facts"]["refs"], item["golden_id"]
    verdicts = judge.judge_records([i["record"] for i in items], FakeJudge())
    for item, verdict in zip(items, verdicts, strict=True):
        expected = item["expected"]
        if expected["pass"] or expected["bucket"] == "accuracy":  # the provable verdicts
            assert verdict.pass_ == expected["pass"], item["golden_id"]
        if expected["bucket"] == "plain":  # the grade cap alone cannot fail a note (pass >= 10)
            assert verdict.scores.plain <= 1, item["golden_id"]


def test_summary_reports_buckets_needs_edit_and_ledger(scores: list[JudgeScore], fake_run) -> None:
    summary = json.loads((fake_run.out / "judge_summary.json").read_text(encoding="utf-8"))
    assert summary["count"] == len(scores) and 0 <= summary["pass_rate"] <= 1
    assert set(summary["mean_scores"]) == set(DIMENSIONS)
    assert summary["needs_human_edit"] == [s.explanation_id for s in scores if not s.pass_]
    entries = ledger.read(fake_run.out / "judge.jsonl")
    turns = [e for e in entries if e.actor == "model"]
    assert len(turns) == len(scores)
    assert all(e.model_id == FAKE_MODEL and e.prompt_versions == {"judge": 1} for e in turns)
    metrics = json.loads((fake_run.out / "metrics.json").read_text(encoding="utf-8"))
    assert "usage_judge" in metrics and "usage_explain" in metrics


def test_calibration_file_has_ten_items_for_the_clinical_teammate() -> None:
    status = judge.calibration_status()
    assert status["items"] == 10
    assert status["graded"] <= 10 and status["agreement"] <= status["graded"]


def test_judge_golden_writes_scores_summary_and_ledger_to_a_new_dir(tmp_path) -> None:
    out = tmp_path / "golden-judge"
    summary = judge.judge_golden(FakeJudge(), out, echo=lambda *_: None)
    assert summary["count"] == 12 and summary["golden_agreement"].endswith("/12")
    assert (out / "judge_scores.json").is_file() and (out / "judge_summary.json").is_file()
    assert len(ledger.read(out / "judge.jsonl")) == 12
    written = json.loads((out / "judge_summary.json").read_text(encoding="utf-8"))
    assert written["golden_agreement"] == summary["golden_agreement"]


def test_judge_calibration_books_its_calls_in_their_own_ledger(tmp_path) -> None:
    out = tmp_path / "golden-judge"
    status = judge.judge_calibration(FakeJudge(), out, echo=lambda *_: None)
    assert status["items"] == 10 and (out / "calibration_scores.json").is_file()
    entries = ledger.read(out / "calibration.jsonl")
    assert len(entries) == 10 and {e.run_id for e in entries} == {"calibration"}
    assert status["usage"]["iterations"] == 10  # the fake model has no price, so no cost check
    assert status["usage"]["tokens"]["input"] == 10 * entries[0].usage.input


def test_a_rider_note_without_its_new_times_scores_actionable_zero(records: list[dict]) -> None:
    record = copy.deepcopy(next(r for r in records if r["explanation"]["audience"] == "rider"))
    record["explanation"]["what_changed"] = "Your day changed a little."
    score = judge.override(record, _raw(record["explanation_id"]))
    assert score.scores.actionable == 0 and "missing" in score.rationale


def test_a_note_that_does_not_name_the_contact_caps_complete(records: list[dict]) -> None:
    record = copy.deepcopy(records[0])
    record["explanation"]["why"] = "The vans were moved around. Call the number on file."
    score = judge.override(record, _raw(record["explanation_id"]))
    assert score.scores.complete <= 1 and record["facts"]["contact"] in score.rationale


# --- the batch path -------------------------------------------------------------------------------


def test_batch_prices_are_half_of_sync() -> None:
    from c2r.llm import Usage, cost_usd

    usage = Usage(input=1000, cache_read=4000, cache_write=0, output=300)
    assert (
        cost_usd("claude-fable-5-1", usage, batch=True) == cost_usd("claude-fable-5-1", usage) / 2
    )
    assert cost_usd(FAKE_MODEL, usage, batch=True) == 0.0


def test_a_completion_with_bad_json_is_invalid_json() -> None:
    from types import SimpleNamespace

    from c2r.llm import _completion

    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=10,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            output_tokens=2,
        ),
        content=[SimpleNamespace(type="text", text="not json")],
        stop_reason="end_turn",
    )
    done = _completion("claude-fable-5-1", response, batch=True)
    assert done.data is None and done.stop_reason == "invalid_json"
    assert done.cost_usd == cost_of(done.usage) / 2


def cost_of(usage) -> float:
    from c2r.llm import cost_usd

    return cost_usd("claude-fable-5-1", usage)


@pytest.fixture(scope="module")
def two_runs(records: list[dict], fake_run, tmp_path_factory: pytest.TempPathFactory) -> list:
    del records  # explanations.json exists once the explainer has run
    import shutil

    root = tmp_path_factory.mktemp("batch")
    dirs = [root / "a", root / "b"]
    for target in dirs:
        shutil.copytree(fake_run.out, target)
    return dirs


def test_judge_batch_writes_every_run_from_one_batch(two_runs: list, tmp_path) -> None:
    from c2r.llm import FakeBatchWriter

    writer = FakeBatchWriter()
    state_path = tmp_path / "judge_batch.json"
    outcome = judge.judge_batch(two_runs, writer, state_path, echo=lambda *_: None, poll_s=0)
    assert outcome["collected"] is True and outcome["batch_id"] == "fake-batch-1"
    items = writer.batches["fake-batch-1"]
    assert {i.custom_id.split(":")[0] for i in items} == {"0", "1"}
    assert outcome["items"] == len(items) == outcome["results"]
    for run_dir in two_runs:
        scores = json.loads((run_dir / "judge_scores.json").read_text(encoding="utf-8"))
        summary = json.loads((run_dir / "judge_summary.json").read_text(encoding="utf-8"))
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        assert len(scores) == len(items) // 2 and all("pass" in s for s in scores)
        assert summary["batch_id"] == "fake-batch-1"
        assert metrics["usage_judge"]["batch_id"] == "fake-batch-1"
        assert metrics["usage_judge"]["model_id"] == FAKE_MODEL
        entries = ledger.read(run_dir / "judge.jsonl")
        assert len(entries) == len(scores)
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["collected"] is True and saved["runs"] == [str(p) for p in two_runs]


def test_judge_collect_finishes_a_batch_from_the_saved_state(two_runs: list, tmp_path) -> None:
    from c2r.llm import BatchItem, FakeBatchWriter

    writer = FakeBatchWriter()
    records = json.loads((two_runs[0] / "explanations.json").read_text(encoding="utf-8"))
    system, _ = judge._prompt()
    items = [
        BatchItem(f"0:{r['explanation_id']}", system, judge._user(r), judge.SCHEMA) for r in records
    ]
    batch_id = writer.submit(items[:-1])  # one verdict never comes back
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"batch_id": batch_id, "runs": [str(two_runs[0])], "collected": False}),
        encoding="utf-8",
    )
    outcome = judge.judge_collect(state_path, writer, echo=lambda *_: None)
    scores = outcome["summaries"][str(two_runs[0])]
    assert scores["count"] == len(records)
    missing = records[-1]["explanation_id"]
    assert missing in scores["needs_human_edit"]
    written = json.loads((two_runs[0] / "judge_scores.json").read_text(encoding="utf-8"))
    assert any(
        "missing from the batch" in s["rationale"]
        for s in written
        if s["explanation_id"] == missing
    )
