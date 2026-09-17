"""The baseline scenario on seed 42 against its golden metrics (handoff section 9.B)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "evals" / "golden" / "baseline.json"
SCENARIO = ROOT / "evals" / "scenarios" / "baseline.json"
WAIT_KEYS = ("mean_post_wait", "p90_post_wait", "wait_min_total")
MIN_BAND = 1.0  # minutes: the tolerance floor when the golden value itself is tiny


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def golden() -> dict:
    if not GOLDEN.is_file():
        pytest.fail(
            f"{GOLDEN} is missing; run `uv run python evals/run_evals.py --golden-baseline`"
        )
    return _load(GOLDEN)


@pytest.fixture(scope="module")
def measured(fake_run) -> dict:
    metrics = _load(fake_run.out / "metrics.json")
    after, before = metrics["after"], metrics["before"]
    returns = len(fake_run.result.state.return_trips())
    return {
        "before": before,
        "after": after,
        "elapsed_s": metrics["elapsed_s"],
        "wait_removed_share": 1 - after["wait_min_total"] / before["wait_min_total"],
        "queue_share": after["riders_flagged"] / returns,
        "violations": fake_run.result.result.violations,
    }


def test_scenario_file_names_the_baseline() -> None:
    scenario = _load(SCENARIO)
    assert scenario["name"] == "baseline" and scenario["event"] is None and scenario["wired"]


def test_after_metrics_within_golden_tolerance(golden: dict, measured: dict) -> None:
    band = golden["tolerance"]
    for key in WAIT_KEYS + ("equity_gap", "vehicle_min"):
        want, got = float(golden["after"][key]), float(measured["after"][key])
        allowed = max(abs(want) * band, MIN_BAND)
        assert abs(got - want) <= allowed, f"{key}: golden {want}, measured {got}, band {allowed}"
    assert measured["after"]["riders_flagged"] == golden["after"]["riders_flagged"]
    assert measured["after"]["conflicts"] == 0
    assert measured["violations"] == []


def test_beating_golden_by_more_than_the_band_needs_a_re_golden_review(
    golden: dict, measured: dict
) -> None:
    want, got = float(golden["after"]["wait_min_total"]), float(measured["after"]["wait_min_total"])
    assert got >= want * (1 - golden["tolerance"]) or want - got <= MIN_BAND, (
        f"wait minutes {got} beat golden {want} by more than {golden['tolerance']:.0%}: "
        "re-golden review, not an automatic update (run --golden-baseline after the review)"
    )


def test_before_metrics_match_the_golden_day(golden: dict, measured: dict) -> None:
    assert measured["before"] == golden["before"], "the synthetic day changed; regenerate golden"


def test_required_outcomes_from_the_handoff(measured: dict) -> None:
    required = _load(SCENARIO)["required"]
    after = measured["after"]
    assert after["mean_post_wait"] <= required["mean_post_wait_max"]
    assert after["p90_post_wait"] <= required["p90_post_wait_max"]
    assert measured["wait_removed_share"] >= required["wait_removed_share_min"]
    assert measured["queue_share"] <= required["queue_share_max"]
    assert measured["elapsed_s"] <= required["runtime_s_max"]
