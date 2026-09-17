"""The gate's recorded receipts: judge agreement on the golden set, demo cost and runtime.

The gate cannot call the API in under 60 s, so it checks the receipts ``--record`` copied from
the artefacts of the last live passes, and proves the judge prompt they were measured on is
the one on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from c2r.judge import PROMPT
from c2r.orchestrator import frontmatter, sha

ROOT = Path(__file__).resolve().parents[2]
RECEIPTS = ROOT / "evals" / "golden" / "receipts.json"
AGREEMENT_FLOOR = 11  # of 12 (>= 90 %)
COST_MAX_USD = 4.0
DAY_S_MAX = 90
REPLAN_S_MAX = 30


@pytest.fixture(scope="module")
def receipts() -> dict:
    if not RECEIPTS.is_file():
        pytest.fail(f"{RECEIPTS} is missing; run `uv run python evals/run_evals.py --record`")
    return json.loads(RECEIPTS.read_text(encoding="utf-8"))


def test_judge_agreement_on_the_golden_set(receipts: dict) -> None:
    judge = receipts["judge_golden"]
    assert judge["count"] == 12
    assert judge["agreed"] >= AGREEMENT_FLOOR, judge["agreement"]
    assert judge["agreement"] == f"{judge['agreed']}/{judge['count']}"


def test_judge_receipt_was_measured_on_the_prompt_on_disk(receipts: dict) -> None:
    judge = receipts["judge_golden"]
    assert judge["prompt"] == PROMPT.name
    _, body = frontmatter(PROMPT.read_text(encoding="utf-8"))
    assert judge["prompt_sha"] == sha(body.strip()), (
        f"{PROMPT.name} changed since the golden set was judged; run --judge-only"
    )


def test_demo_cost_and_runtime(receipts: dict) -> None:
    demo = receipts["demo"]
    assert demo["cost_usd"] <= COST_MAX_USD
    assert demo["cost_usd"] == round(demo["day"]["cost_usd"] + demo["replan"]["cost_usd"], 4)
    assert demo["day"]["elapsed_s"] <= DAY_S_MAX
    assert demo["replan"]["elapsed_s"] <= REPLAN_S_MAX


def test_receipts_name_their_sources(receipts: dict) -> None:
    for entry in (receipts["judge_golden"], receipts["demo"]["day"], receipts["demo"]["replan"]):
        assert entry["source"].startswith("runs/")
    assert receipts["recorded"] and receipts["git_sha"]
