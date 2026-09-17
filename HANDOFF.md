# Session handoff

Updated 2026-09-17 during CP1 (solver + verifier). Start a fresh session from here.

## Built this session
Committed first (4 commits, each under 400 changed lines in `src/`):
- `src/c2r/state.py`: `State` loader, `scheduled_ready`, `actual_ready`.
- `src/c2r/verify.py`: `ride_checks.py` renamed and extended to H1-H13, `schedule_hash`,
  `verify(candidate, baseline, version)`; H7 anchors on the baseline request.
- `src/c2r/routing.py`: `Plan`/`Batch`, `plan_from_manifest`, `committed_vans`, `build_manifest`
  (byte-for-byte rebuild of the baseline from its own plan).
- `src/c2r/parties/{__init__,unit,broker}.py`: deterministic parties with reason codes and hints.
- `evals/invariants/test_verify.py`, `test_routing.py`, `test_parties.py`.

Committed at the end of the session (4 more commits, 8 for CP1 in all):
- `src/c2r/moves.py`: `apply`, `j_score`, `honest_opens`, `_moves`, window fixes.
- `src/c2r/review.py`: `legal_options`, `review_queue` (the human-review items).
- `src/c2r/solver.py`: `generate_candidates`, greedy `solve`, closing window pass, run
  artefacts, CLI `python -m c2r.solver <data_dir> --out runs/cp1`.
- `src/c2r/routing.py` (`Infeasible`, any-leg van pool, shallow copies), `src/c2r/verify.py`
  (`is_will_call`; H7 anchors will-call riders on the roster's actual ready time).
- `src/c2r/viz/timeline.py`: before/after Gantt as one self-contained HTML file.
- `evals/invariants/test_invariants.py` I1-I15 on the after-state; new routing/party/verify tests.
- `Makefile`: `solve`, `timeline`; `demo` runs both. `docs/cp1-decisions.md`, `docs/llms.txt`,
  CLAUDE.md lessons 1-2.

Committed after the user's follow-up (2 more commits, 10 for CP1 in all):
- `.claude/hooks/k2_guard.py` (eighth hook): refuses a `git commit` whose `src/` diff exceeds 400
  lines; tests in `evals/repo/test_hooks.py` drive it against a throwaway git repo.
- `src/c2r/metrics.py`: `vehicle_min` counts on-task minutes (rider aboard or loading), not the
  first-to-last-stop span; `evals/invariants/test_metrics.py`.

## Decisions made (details and numbers in docs/cp1-decisions.md)
1. A shift's return pool is every van the baseline already sends for that shift's riders, either
   leg (all five on seed 42). One van per shift made the target physically unreachable.
2. A return with no standing window is a will-call whatever its status; its request time becomes
   the actual ready time when scheduled. Standing orders keep the baseline request, read from the
   baseline in verify and the broker party.
3. H6 keeps scheduled ready; the solver plans against actual ready.
4. Sub-codes H9_SHIFT/H9_ROUTE/BROKER_EARLIEST report as H9 (schema enum).
5. Windows follow the van: touched returns are re-timed to where the van arrives, inside the
   ADA band; a closing pass re-times riders whose pickup drifted.
6. Riders still over 45 min after the loop are held for will-call on the record (`H<n>` bundles,
   metrics printed before any hold). On seed 42 nobody is held.
7. The step cap is `stop.max_iterations x max_moves_per_bundle`; the early stop needs every
   non-stretcher return scheduled.
8. A queued rider with a legal, accepted candidate gets a `BROKER_POLICY` item naming the bundle
   and both J values, judged on the final state, not `NO_FEASIBLE_WINDOW`.
9. Lesson 3 (will-call opens) was dropped again: it duplicated code comments.
10. Vehicle minutes are on-task minutes (`metrics._busy_minutes`): the span definition charged
    P31f's evening ride five idle hours and J held the rider. Before is now 523, not 3434; B
    should re-check the 0.05 weight. The K2 hook fails open outside a git repo and measures the
    working tree plus untracked files when the same command runs `git add`.

## Artifacts
- `runs/cp1/`: schedule_before/after.json, verify_after.json, bundles.json, review_queue.json,
  metrics.json, timeline.html. Git-ignored; `make demo` regenerates them.
- Seed 42: mean post-wait 70.21 -> 2.71, p90 131 -> 13, equity gap 32.14 -> 1.27,
  flagged 4 -> 1 (stretcher only), vehicle minutes 523 -> 566, J 1117.15 -> 137.3, 14 bundles,
  0 violations, ~13 s.

## Acceptance status
- `uv run pytest evals/invariants -q`: 60 passed (17.2 s).
- `make gate`: 197 passed, GATE PASS (54.0 s); `uv run pytest evals/repo -q`: 109 passed.
- `make solve`: 0 violations, after beats baseline, target (mean <= 25, p90 <= 45) met.
- `make timeline`: runs/cp1/timeline.html, two panels, no external assets.
- Reviews: five reviewer passes (verifier; routing+parties; solver; solver fixes + timeline;
  vehicle-minute metric), every finding fixed or recorded in docs/cp1-decisions.md. Nothing waived.

## What's next
1. Open `runs/cp1/timeline.html` in a browser and eyeball it (not done: no browser this session).
2. Tell B that vehicle minutes now count on-task time (before 523, was 3434 as a span) and ask
   whether the 0.05 weight still stands.
3. CP2 starts with `/kickoff cp2`; `generate_candidates(baseline, state, plan, side, k=6)` is
   the tool the mediator calls, and `unit.respond` / `broker.respond` are the parties.
