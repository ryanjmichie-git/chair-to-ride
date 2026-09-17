---
name: run-evals
description: Run the eval suite and summarise failures by invariant, scenario, or judge bucket.
argument-hint: "[--gate|--full|--judge-only]"
allowed-tools:
  - Bash
  - Read
---

# /run-evals

1. Run `uv run python evals/run_evals.py $ARGUMENTS` (default `--gate` when `$ARGUMENTS` is empty).
2. Summarise failures grouped by invariant id (I1–I20), scenario name, or judge rubric bucket — whichever the output contains.
