# CP1 — Solver + verifier

## Goal
Prove the after-schedule can be computed and legally checked with deterministic code only — no LLM in this checkpoint.

## Files
- `src/c2r/solver.py` — candidate generation (chair shifts ±15/±30, window shifts, vehicle reassignment, pairing, 2-opt resequence), scores by `J`, returns top-6 bundles.
- `src/c2r/verify.py` — recomputes routes and H1–H13 from scratch on a candidate state; returns violations + metrics + hash. Pure function.
- `src/c2r/parties/unit.py`, `src/c2r/parties/broker.py` — deterministic accept/reject against `config/unit_policy.md` / `config/broker_policy.md`, with reason codes and hints.
- `evals/invariants/test_*.py` — I1–I15.

## Out of scope
`orchestrator.py`, any LLM call, explanations, judge, perturbation events (`perturb.py`) — CP2/CP3.

## Definition of done
- Invariants I1–I15 all green.
- Running the solver + verifier on `data/synthetic/42/` produces an after-state with 0 hard-constraint violations and post-wait metrics better than the baseline (mean ≤ 25, p90 ≤ 45 is the target, not required to hit here).
- `timeline.html` renders both the before and after Gantt from the same run.
- C has run `/review` on the diff before commit.

## Verification command
```
uv run pytest evals/invariants -q
make gate
```

## PR checklist
- [ ] C1 — test output pasted
- [ ] C5 — reviewer findings attached and addressed, or waived with reason
- [ ] C8 — a lesson or a hook added if a misunderstanding caused a bug
- [ ] K2 — diff ≤ 400 changed lines in `src/`
