# CP4 — Evals + freeze

## Goal
The gate is fast and green, the full suite is kicked off, and the code freezes except viz.

## Files
- `evals/run_evals.py` — `--full` path (15 runs, judge via Batch, 1-h cache).
- `cost_report.md` — tokens by type, cache-read share, dollars by model.
- `/doctor` pass to prune `CLAUDE.md`.

## Out of scope
Rehearsal, backup recording, `demo_script.md` finalization (CP5).

## Definition of done
- `evals/run_evals.py --gate` completes in < 60 s: invariants 100%, baseline scenario within golden tolerance, judge pass rate ≥ 90% on the 12-item golden set, cost ≤ $4/run, runtime ≤ 90 s.
- `--full` (15 runs) is kicked off and running, not blocking the gate.
- Code frozen except `viz/`: any further `src/c2r/*` edit requires a spec update and reviewer sign-off.
- `CLAUDE.md` still ≤ 60 lines after `/doctor`.

## Verification command
```
time uv run python evals/run_evals.py --gate
uv run python evals/run_evals.py --full &
```

## PR checklist
- [ ] C1 — test output pasted
- [ ] C5 — reviewer findings attached and addressed, or waived with reason
- [ ] C8 — a lesson or a hook added if a misunderstanding caused a bug
- [ ] K2 — diff ≤ 400 changed lines in `src/`
