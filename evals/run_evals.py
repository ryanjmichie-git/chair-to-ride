"""Eval entry point; --gate runs the repo and data suites and prints one summary line."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _count(output: str, word: str) -> int:
    found = re.findall(rf"(\d+) {word}", output)
    return int(found[-1]) if found else 0


def _gate() -> int:
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "evals/repo", "evals/data", "-q",
         "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = proc.stdout + proc.stderr
    print(output, end="" if output.endswith("\n") else "\n")
    elapsed = round(time.monotonic() - started, 1)
    passed = _count(output, "passed")
    if proc.returncode == 0:
        print(f"GATE PASS ({passed} passed, {elapsed}s)")
    else:
        print(f"GATE FAIL ({passed} passed, {_count(output, 'failed')} failed, {elapsed}s)")
    return proc.returncode


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
        print("not available until CP3")
        return 3
    return _gate()


if __name__ == "__main__":
    sys.exit(main())
