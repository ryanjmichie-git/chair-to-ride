---
name: run-demo
description: Run the demo and summarise the resulting metrics and cost.
allowed-tools:
  - Bash
  - Read
  - Glob
---

# /run-demo

1. Run `make demo`.
2. Find the newest `runs/<run_id>/metrics.json`. Summarise it (mean/p90 post-wait, wait-minutes removed, riders flagged, equity gap) and the cost lines from `runs/<run_id>/ledger.jsonl` if present.
3. If no run directory exists yet, summarise the baseline table from `make baseline` instead.
