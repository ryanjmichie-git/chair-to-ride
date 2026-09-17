"""The --full runner offline: scenario files, NOT WIRED cells, resume, one judge batch."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from c2r import explain
from c2r.llm import FakeWriter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evals"))

import suite

DATA = ROOT / "data" / "synthetic" / "42"
SECTION = "CHAIR-TO-RIDE-HANDOFF.md section 9.B"


def test_six_scenario_files_two_wired() -> None:
    found = suite.scenarios()
    assert [s["name"] for s in found[:2]] == ["baseline", "vehicle_breakdown"]
    assert len(found) == 6
    for scenario in found:
        assert scenario["source"].startswith(SECTION)
        assert isinstance(scenario["wired"], bool) and scenario["required"]
        if not scenario["wired"]:
            assert scenario["not_wired_reason"]
        if scenario["event"] is not None:
            assert scenario["event"]["type"] in {
                "vehicle_down",
                "chair_down",
                "late_arrival",
                "add_on_patient",
                "travel_slowdown",
            }
    assert [s["name"] for s in found if s["wired"]] == ["baseline", "vehicle_breakdown"]


@pytest.fixture(scope="module")
def suite_run(fake_run, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, int]:
    """One seed offline: the baseline cell is seeded from the shared fake run, the rest runs."""
    runs = tmp_path_factory.mktemp("full-fake")
    baseline = runs / "42" / "baseline"
    shutil.copytree(fake_run.out, baseline)
    explain.explain_run(baseline, FakeWriter(), echo=lambda *_: None)
    metrics = json.loads((baseline / "metrics.json").read_text(encoding="utf-8"))
    cell = {
        "scenario": "baseline",
        "seed": 42,
        "dir": str(baseline),
        "wired": True,
        "status": "ok",
        "elapsed_s": metrics["elapsed_s"],
        "cost_usd": 0.0,
        "cache_read_share": metrics["usage"]["cache_read_share"],
        "checks": {"seeded": True},
        "required_met": True,
    }
    (baseline / "cell.json").write_text(json.dumps(cell), encoding="utf-8")
    code = suite.full([42], fake=True, echo=lambda *_: None, runs=runs)
    return runs, code


def test_full_offline_passes_the_wired_scenarios(suite_run: tuple[Path, int]) -> None:
    runs, code = suite_run
    summary = json.loads((runs / "summary.json").read_text(encoding="utf-8"))
    assert code == 0 and summary["verdict"] == "PASS"
    assert summary["wired_scenarios"] == ["baseline", "vehicle_breakdown"]
    assert len(summary["not_wired"]) == 4
    assert summary["cells"] == 6 and summary["cells_ok"] == 2
    breakdown = summary["scenarios"]["vehicle_breakdown"]["cells"]["42"]
    assert breakdown["status"] == "ok" and breakdown["required_met"]
    assert breakdown["checks"]["none_stranded"] and breakdown["checks"]["replan_s_max"]
    assert (runs / "42" / "vehicle_breakdown" / "explanations.json").is_file()


def test_not_wired_cells_cost_nothing_and_say_why(suite_run: tuple[Path, int]) -> None:
    runs, _ = suite_run
    for name in ("chair_outage", "late_patient", "over_capacity_day", "travel_slowdown"):
        cell = json.loads((runs / "42" / name / "cell.json").read_text(encoding="utf-8"))
        assert cell["status"] == "not_wired" and cell["reason"]
        assert not (runs / "42" / name / "metrics.json").exists()
    summary = json.loads((runs / "summary.json").read_text(encoding="utf-8"))
    assert summary["scenarios"]["chair_outage"]["status"] == "NOT WIRED"


def test_one_judge_batch_covers_every_note(suite_run: tuple[Path, int]) -> None:
    runs, _ = suite_run
    state = json.loads((runs / "judge_batch.json").read_text(encoding="utf-8"))
    assert state["collected"] is True and state["batch_id"] == "fake-batch-1"
    assert len(state["runs"]) == 2
    notes = 0
    for cell_dir in (runs / "42" / "baseline", runs / "42" / "vehicle_breakdown"):
        scores = json.loads((cell_dir / "judge_scores.json").read_text(encoding="utf-8"))
        summary = json.loads((cell_dir / "judge_summary.json").read_text(encoding="utf-8"))
        assert summary["batch_id"] == "fake-batch-1"
        notes += len(scores)
    assert notes == state["items"] == state["results"]
    progress = (runs / "progress.log").read_text(encoding="utf-8")
    assert "FULL PASS" in progress and "judge batch fake-batch-1" in progress


def test_a_second_run_skips_finished_cells_and_the_collected_batch(
    suite_run: tuple[Path, int],
) -> None:
    runs, _ = suite_run
    lines: list[str] = []
    code = suite.full([42], fake=True, echo=lines.append, runs=runs)
    assert code == 0
    assert sum("done earlier, skipped" in line for line in lines) == 2
    assert any("collected earlier" in line for line in lines)


def test_collect_rewrites_the_summary_from_the_cells(suite_run: tuple[Path, int]) -> None:
    runs, _ = suite_run
    (runs / "summary.json").unlink()
    assert suite.collect(fake=True, echo=lambda *_: None, runs=runs) == 0
    assert (runs / "summary.json").is_file()


def test_the_live_suite_refuses_to_start_without_a_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    lines: list[str] = []
    assert suite.full([42], fake=False, echo=lines.append, runs=tmp_path) == 2
    assert lines and "FULL SKIP" in lines[0]
    assert not any(tmp_path.iterdir())
