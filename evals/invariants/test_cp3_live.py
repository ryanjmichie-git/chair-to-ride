"""CP3 on the wire: a live re-plan inside 30 s, live explanations and a live judge on it, and
the judge's agreement with the golden set. ``llm``-marked: the gate deselects this module.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from c2r import explain, judge, perturb
from c2r.llm import AnthropicMediator, AnthropicWriter

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY"),
]
DATA = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "42"
SOURCE = Path(__file__).resolve().parents[2] / "runs" / "cp2"


@pytest.fixture(scope="module")
def replan(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not (SOURCE / "schedule_after.json").is_file():
        pytest.skip("runs/cp2 has no finished run; run make mediate first")
    out = tmp_path_factory.mktemp("cp3-live")
    event = perturb.load_event(DATA, "vehicle_down", "13:40")
    mediator = AnthropicMediator(effort="low", timeout=perturb.TURN_TIMEOUT_S, retries=0)
    result = perturb.run(DATA, SOURCE, out, event, mediator, echo=lambda *_: None)
    assert not result.result.violations
    return out


def test_live_replan_inside_thirty_seconds(replan: Path) -> None:
    metrics = json.loads((replan / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["elapsed_s"] <= 30, metrics["elapsed_s"]
    assert metrics["usage"]["model_id"] == "claude-fable-5-1"
    affected = json.loads((replan / "event.json").read_text(encoding="utf-8"))["affected"]
    manifest = json.loads((replan / "schedule_after.json").read_text(encoding="utf-8"))["manifest"]
    queued = {i["subject"] for i in json.loads((replan / "review_queue.json").read_text("utf-8"))}
    for trip in manifest["trips"]:
        if trip["trip_id"] in affected:
            re_homed = trip["status"] == "scheduled" and trip["vehicle_id"] != "V3"
            assert re_homed or trip["trip_id"] in queued, trip["trip_id"]


def test_live_explanations_cite_only_their_refs_and_pass_the_judge(replan: Path) -> None:
    records = explain.explain_run(replan, AnthropicWriter(), echo=lambda *_: None)
    assert records
    for record in records:
        assert explain.check_numbers(record) == [], record["explanation_id"]
        assert explain.missing_times(record) == [], record["explanation_id"]
    verdicts = judge.judge_run(
        replan,
        AnthropicWriter(model=judge.MODEL, effort=judge.EFFORT, max_tokens=1200),
        echo=lambda *_: None,
    )
    summary = json.loads((replan / "judge_summary.json").read_text(encoding="utf-8"))
    assert summary["count"] == len(records)
    assert sum(1 for v in verdicts if v.pass_) >= len(verdicts) - 1, summary["needs_human_edit"]


def test_live_judge_agrees_with_the_golden_set(tmp_path: Path) -> None:
    summary = judge.judge_golden(
        AnthropicWriter(model=judge.MODEL, effort=judge.EFFORT, max_tokens=1200),
        tmp_path / "golden",
        echo=lambda *_: None,
    )
    agreed, total = (int(x) for x in summary["golden_agreement"].split("/"))
    assert total == 12 and agreed >= 11, summary["disagreements"]
