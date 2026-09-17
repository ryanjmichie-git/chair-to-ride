"""Eval entry point; --gate runs the repo and data suites and prints one summary line.

--judge-only scores the 12-item golden explanation set with the live judge (Fable 5.1, low)
and reports agreement with the hand verdicts, plus the clinical teammate's calibration status.
Tests marked ``llm`` call the API and are reserved for the full pass (--full, CP4).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_DIRS = ("evals/repo", "evals/data", "evals/invariants")


def _count(output: str, word: str) -> int:
    found = re.findall(rf"(\d+) {word}", output)
    return int(found[-1]) if found else 0


def _gate() -> int:
    present = [d for d in GATE_DIRS if any((ROOT / d).glob("test_*.py"))]
    if not present:
        print("GATE FAIL (no gate test directories found)")
        return 1
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *present, "-q", "-m", "not llm", "-p", "no:cacheprovider"],
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
        print(f"GATE PASS ({names}: {passed} passed, {elapsed}s)")
    elif passed or failed:
        print(f"GATE FAIL ({names}: {passed} passed, {failed} failed, {elapsed}s)")
    else:
        print(f"GATE FAIL (pytest exit {proc.returncode})")
        print("\n".join(output.splitlines()[-30:]))
    return proc.returncode


AGREEMENT_FLOOR = 11  # of 12: the CP4 gate's "judge pass rate >= 90% on the golden set"


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
    calls = summary["usage"]["iterations"] + calibration["items"]
    cost = summary["usage"]["cost_usd"]
    elapsed = round(time.monotonic() - started, 1)
    verdict = "PASS" if agreed >= AGREEMENT_FLOOR else "FAIL"
    print(
        f"JUDGE {verdict} (golden agreement {summary['golden_agreement']}, {calls} calls, "
        f"golden cost ${cost:.2f}, {elapsed}s; {out / 'judge_summary.json'})"
    )
    return 0 if verdict == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--gate", action="store_true")
    mode.add_argument("--full", action="store_true")
    mode.add_argument("--judge-only", action="store_true")
    args = parser.parse_args()
    if args.full:
        print("not available until CP4")
        return 3
    if args.judge_only:
        return _judge_only()
    return _gate()


if __name__ == "__main__":
    sys.exit(main())
