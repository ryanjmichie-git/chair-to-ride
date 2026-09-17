"""Eval entry point.

``--gate`` runs the offline suites in parallel (repo, data, invariants, scenarios) and prints one
summary line with the recorded receipts (judge agreement, demo cost and runtime). It must finish
under 60 s; the Stop hook runs it.
``--judge-only`` scores the 12-item golden set with the live judge and refreshes the receipts.
``--record`` rewrites ``evals/golden/receipts.json`` from the run artefacts, never by hand.
``--golden-baseline`` rewrites ``evals/golden/baseline.json`` from an offline mediator run.
``--full`` runs the scenario suite live (``evals/suite.py``); ``--full-collect`` finishes a
judge batch that outlived the process.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GATE_DIRS = ("evals/repo", "evals/data", "evals/invariants", "evals/scenarios")
WORKERS = 4  # measured 2026-09-17 on a 10-core laptop: 95 s serial; 4 workers beat 10 once the solver processes throttle the clock
GOLDEN = ROOT / "evals" / "golden"
RECEIPTS = GOLDEN / "receipts.json"
BASELINE_GOLDEN = GOLDEN / "baseline.json"
DATA = ROOT / "data" / "synthetic" / "42"
AGREEMENT_FLOOR = 11  # of 12: the CP4 gate's "judge pass rate >= 90% on the golden set"


def _today() -> str:
    return dt.datetime.now(tz=dt.UTC).date().isoformat()


def _count(output: str, word: str) -> int:
    found = re.findall(rf"(\d+) {word}", output)
    return int(found[-1]) if found else 0


def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def receipts_line() -> str:
    """The recorded receipts in one line, or a note that they are missing."""
    if not RECEIPTS.is_file():
        return "receipts: none recorded (run --record)"
    r = _load(RECEIPTS)
    judge, demo = r["judge_golden"], r["demo"]
    return (
        f"receipts {r['recorded']}: judge golden {judge['agreement']}, demo ${demo['cost_usd']:.2f} "
        f"(day {demo['day']['elapsed_s']:g} s, re-plan {demo['replan']['elapsed_s']:g} s)"
    )


def _gate() -> int:
    present = [d for d in GATE_DIRS if any((ROOT / d).glob("test_*.py"))]
    if not present:
        print("GATE FAIL (no gate test directories found)")
        return 1
    started = time.monotonic()
    sys.path.insert(0, str(ROOT / "evals"))
    import fakerun

    try:  # built serially here, so its own clock is measured on an idle machine
        fakerun.ensure(echo=print)
    except (RuntimeError, TimeoutError) as exc:
        print(f"GATE FAIL (shared fake run: {exc})")
        return 1
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *present,
            "-q",
            "-m",
            "not llm",
            "-p",
            "no:cacheprovider",
            "-n",
            str(WORKERS),
            "--dist",
            "loadscope",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = proc.stdout + proc.stderr
    print(output, end="" if output.endswith("\n") else "\n")
    elapsed = round(time.monotonic() - started, 1)
    names = ", ".join(present)
    passed = _count(output, "passed")
    failed = _count(output, "failed")
    if proc.returncode == 0:
        print(f"GATE PASS ({names}: {passed} passed, {elapsed}s; {receipts_line()})")
    elif passed or failed:
        print(f"GATE FAIL ({names}: {passed} passed, {failed} failed, {elapsed}s)")
    else:
        print(f"GATE FAIL (pytest exit {proc.returncode})")
        print("\n".join(output.splitlines()[-30:]))
    return proc.returncode


# --- receipts: numbers copied from artefacts, never typed --------------------------------------


def _run_cost(metrics: dict[str, Any]) -> float:
    return round(
        sum(
            float(metrics[key]["cost_usd"])
            for key in ("usage", "usage_explain", "usage_judge")
            if key in metrics
        ),
        4,
    )


def _judge_receipt(golden_dir: Path) -> dict[str, Any]:
    summary = _load(golden_dir / "judge_summary.json")
    first = json.loads((golden_dir / "judge.jsonl").read_text(encoding="utf-8").splitlines()[0])
    prompt = next(k for k in first["input_hashes"] if k.startswith("judge."))
    agreed, count = (int(n) for n in summary["golden_agreement"].split("/"))
    return {
        "golden_set": "golden_explanations.json",
        "golden_set_sha": first["input_hashes"]["golden_explanations.json"],
        "source": golden_dir.relative_to(ROOT).as_posix(),
        "agreement": summary["golden_agreement"],
        "agreed": agreed,
        "count": count,
        "pass_rate": summary["pass_rate"],
        "mean_scores": summary["mean_scores"],
        "prompt": prompt,
        "prompt_sha": first["input_hashes"][prompt],
        "model_id": first["model_id"],
        "effort": first["effort"],
        "cost_usd": summary["usage"]["cost_usd"],
    }


def _demo_receipt(run_dir: Path) -> dict[str, Any]:
    metrics = _load(run_dir / "metrics.json")
    return {
        "source": run_dir.relative_to(ROOT).as_posix(),
        "run_id": metrics.get("run_id"),
        "elapsed_s": metrics["elapsed_s"],
        "cost_usd": _run_cost(metrics),
        "model_id": metrics["usage"]["model_id"],
        "effort": metrics["usage"]["effort"],
        "cache_read_share": metrics["usage"]["cache_read_share"],
    }


def record(
    golden_dir: Path = ROOT / "runs" / "golden-judge",
    day_dir: Path = ROOT / "runs" / "cp2",
    replan_dir: Path = ROOT / "runs" / "cp3",
    path: Path = RECEIPTS,
) -> dict[str, Any]:
    """Write receipts.json from the golden judge run and the demo's day and re-plan runs."""
    from c2r.orchestrator import git_sha

    day, replan = _demo_receipt(day_dir), _demo_receipt(replan_dir)
    receipts = {
        "recorded": _today(),
        "git_sha": git_sha(),
        "judge_golden": _judge_receipt(golden_dir),
        "demo": {
            "day": day,
            "replan": replan,
            "cost_usd": round(day["cost_usd"] + replan["cost_usd"], 4),
        },
    }
    _dump(path, receipts)
    return receipts


def golden_baseline(path: Path = BASELINE_GOLDEN, echo=print) -> dict[str, Any]:
    """Run the offline mediator on seed 42 and write its metrics as the baseline golden."""
    from c2r import orchestrator
    from c2r.llm import FakeMediator

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "baseline"
        result = orchestrator.run(DATA, out, FakeMediator(), echo=lambda *_: None)
        metrics = _load(out / "metrics.json")
    before, after = metrics["before"], metrics["after"]
    returns = len(result.state.return_trips())
    golden = {
        "scenario": "baseline",
        "seed": 42,
        "mediator": FakeMediator.model_id,
        "recorded": _today(),
        "tolerance": 0.15,
        "before": before,
        "after": after,
        "j_before": metrics["j_before"],
        "j_after": metrics["j_after"],
        "return_riders": returns,
        "wait_removed_share": round(1 - after["wait_min_total"] / before["wait_min_total"], 4),
        "queue_share": round(after["riders_flagged"] / returns, 4),
        "bundles_applied": len(result.applied),
    }
    _dump(path, golden)
    echo(f"golden baseline: mean {after['mean_post_wait']}, p90 {after['p90_post_wait']}; {path}")
    return golden


# --- the live judge on the golden set ----------------------------------------------------------


def _judge_only() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("JUDGE SKIP (ANTHROPIC_API_KEY is not set; run under uv run --env-file .env)")
        return 2
    from c2r import judge
    from c2r.llm import AnthropicWriter

    started = time.monotonic()
    out = ROOT / "runs" / "golden-judge"
    client = AnthropicWriter(model=judge.MODEL, effort=judge.EFFORT, max_tokens=1200)
    summary = judge.judge_golden(client, out)
    means = " ".join(f"{d} {v:.2f}" for d, v in summary["mean_scores"].items())
    print(f"judge: golden agreement {summary['golden_agreement']}; mean scores {means}")
    for miss in summary["disagreements"]:
        print(
            f"judge: disagreement {miss['explanation_id']}: expected pass={miss['expected_pass']}, "
            f"judge pass={miss['judge_pass']}: {miss['rationale']}"
        )
    calibration = judge.judge_calibration(client, out)
    print(
        f"judge: calibration {calibration['graded']}/{calibration['items']} graded by the "
        f"clinical teammate; agreement {calibration['agreement']}/{calibration['graded']}"
        + (" (not graded yet)" if not calibration["graded"] else "")
    )
    agreed = int(summary["golden_agreement"].split("/")[0])
    golden_cost = summary["usage"]["cost_usd"]
    calibration_cost = calibration["usage"]["cost_usd"]
    calls = summary["usage"]["iterations"] + calibration["usage"]["iterations"]
    elapsed = round(time.monotonic() - started, 1)
    verdict = "PASS" if agreed >= AGREEMENT_FLOOR else "FAIL"
    if RECEIPTS.is_file():
        receipts = _load(RECEIPTS)
        receipts["judge_golden"] = _judge_receipt(out)
        receipts["recorded"] = _today()
        _dump(RECEIPTS, receipts)
        print(f"judge: receipts refreshed; {RECEIPTS}")
    print(
        f"JUDGE {verdict} (golden agreement {summary['golden_agreement']}, {calls} calls, "
        f"${golden_cost + calibration_cost:.2f} (golden ${golden_cost:.2f}, calibration "
        f"${calibration_cost:.2f}), {elapsed}s; {out / 'judge_summary.json'})"
    )
    return 0 if verdict == "PASS" else 1


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--gate", action="store_true")
    mode.add_argument("--full", action="store_true", help="live scenario suite, see evals/suite.py")
    mode.add_argument("--full-collect", action="store_true", help="finish the suite's judge batch")
    mode.add_argument("--judge-only", action="store_true")
    mode.add_argument("--record", action="store_true", help="rewrite evals/golden/receipts.json")
    mode.add_argument("--golden-baseline", action="store_true")
    parser.add_argument("--fake", action="store_true", help="--full without the API")
    parser.add_argument("--seeds", default="42,43,44", help="--full seeds")
    args = parser.parse_args()
    if args.full or args.full_collect:
        sys.path.insert(0, str(ROOT / "evals"))
        from suite import collect, full

        seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
        return collect(fake=args.fake) if args.full_collect else full(seeds, fake=args.fake)
    if args.judge_only:
        return _judge_only()
    if args.record:
        record()
        print(f"recorded: {receipts_line()}; {RECEIPTS}")
        return 0
    if args.golden_baseline:
        golden_baseline()
        return 0
    return _gate()


if __name__ == "__main__":
    sys.exit(main())
