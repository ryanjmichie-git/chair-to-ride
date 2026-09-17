# Session handoff

Updated 2026-09-17 at the end of CP4 (evals + freeze). Start a fresh session from here.
Every number below is from a command run this session and is also in docs/cp4-decisions.md
with the file it came from.

## Built this session
CP4 landed in seven `cp4:` commits on top of `3284b10` (details in docs/cp4-decisions.md):

- Gate under 60 s: `evals/run_evals.py --gate` runs the four offline suites (`evals/repo`,
  `evals/data`, `evals/invariants`, `evals/scenarios`) with pytest-xdist, 4 workers, loadscope.
  The shared fake mediator run is built serially by `--gate` before pytest and cached on disk
  under `runs/.fake-run-cache/<digest of src/c2r, config, data/synthetic/42,
  prompts/mediator.v1.md, pyproject.toml>` (`evals/fakerun.py`, `evals/conftest.py`).
  `timeutil.to_min` is memoized and `State`'s lookup dicts are cached per instance. The hook
  tests run in-process (`runpy`) and the git-driven ones are their own module. Measured last,
  on a hot laptop: 95 s serial at the start -> 46.9 s cold cache (11.7 s build + 32.8 s tests)
  / 32.2 s warm, 306 tests. Expect 35-56 s of pytest time depending on how hot the machine is;
  before the hook change a hot cold-cache run reached 74.2 s.
- The five gate criteria: `evals/scenarios/test_baseline.py` (the fake run against
  `evals/golden/baseline.json`, written by `--golden-baseline`; the 9.B outcomes) and
  `evals/scenarios/test_receipts.py` (`evals/golden/receipts.json`, written by `--record` from
  `runs/golden-judge`, `runs/cp2`, `runs/cp3`: judge agreement 12/12 with the `judge.v1.md`
  hash, demo $0.83, day 56.9 s, re-plan 13.3 s). The gate's summary line prints the receipts.
- Six section-9.B scenario files in `evals/scenarios/`; `baseline` and `vehicle_breakdown` are
  `wired: true`, the other four `wired: false` with the reason.
- Batch judge: `llm.AnthropicBatchWriter` (one Message Batch, half price, 1-h cached system
  block, results keyed by custom_id), `judge.judge_batch` / `judge_collect` (resumable from
  `judge_batch.json`), `cost_usd(batch=True)`. `orchestrator.build_blocks`/`run` and
  `perturb.run` take `cache_ttl` (block text and hashes unchanged; demo keeps 5 min).
- `--full` (`evals/suite.py`): one cell per seed x scenario under `runs/full/<seed>/<scenario>/`,
  baseline = live day run + Sonnet notes, breakdown = re-plan against that day + notes, one judge
  batch for every note, `summary.json` with `pass^k` per scenario, `progress.log`, resumable;
  `--full --fake` rehearses into `runs/full-fake/`. `make full`, `full-fake`, `full-collect`.
- `cost_report.md` at the repo root from `evals/cost_report.py` (every ledger under `runs/`;
  `make cost-report`). Seeds 43 and 44 generated and committed under `data/synthetic/`.
- Code freeze: `.claude/freeze.json` (`src/c2r/**` frozen, `viz/**` open, waivers with spec and
  reviewer) enforced by `.claude/hooks/code_freeze.py` on Edit|Write and on `git commit`
  (index, or the working tree for `-a`/`--all`/`--include`/pathspec/`git add &&`). Active
  from the final commit.
- CLAUDE.md: one Rules line (the freeze) and one Lessons line added, 39 lines. `/doctor`
  itself is interactive and was not run by this session.

## Decisions made (details in docs/cp4-decisions.md)
1. `--full` scope = wired scenarios only (Ryan, 2026-09-17): baseline + vehicle_breakdown on
   seeds 42/43/44; the four other events need solver/verify work and are reported NOT WIRED.
2. Four xdist workers, not ten: the solver is CPU-bound and the laptop clocks down under all-core
   load (a fixture that takes 10 s alone took 28 s with ten workers).
3. The fake run is cached by input digest; it is a pure function of those inputs, so a hit is
   the same run the gate would have rebuilt.
4. The judge, cost and runtime gate criteria are receipts from the last live artefacts, linked
   by the judge prompt's hash; the gate cannot call the API in under 60 s.
5. A seed the breakdown handler cannot take (outbound leg on the down van) is `not wired for
   seed` and fails the scenario under `pass^k`; the suite never drops a seed to pass.
6. Batch custom ids use a hyphen (`0-E01r`): the API rejected the colon on the first live submit.
7. The freeze file was committed inactive while the src fixes landed and is active in the
   final commit; the plan said "after all src work".
10. The first speed-up commit's message and the docs claimed a digest cache and memoization
   that were not in the code: the bash command carrying them also held an `rm -rf`, the
   danger guard refused the whole command, and only its second half was re-run. The reviewer
   caught it; the code landed in the review-fix commit and the numbers were re-measured. A
   lesson line in CLAUDE.md records it.
11. The hook tests run in-process: 86 interpreter start-ups were 30 s of CPU and the gate's
   critical path; one test still spawns the real interpreter.
8. `test_solver_is_deterministic` does one extra solve (first bundle, j_before, j_after against
   the module's solve); byte-for-byte determinism stays with I18 replay.
9. Money: $2.31 for the live suite (approved estimate $5-8; two of six live cells did not run),
   $0 offline. `cost_report.md` totals $5.68 across all ledgers since CP2.

## Artifacts (git-ignored; the Makefile regenerates them)
- `runs/full/`: `42/baseline` ($1.21, 71.4 s loop, 16 notes 100 % judge pass),
  `42/vehicle_breakdown` ($0.23, 13.8 s, 4 notes 100 %), `43/baseline` ($1.43, 88.9 s, 19 notes
  100 %), `44/baseline` ($1.20, 61.8 s, 17 notes 94 %, `E28r` needs a human edit);
  `43/vehicle_breakdown` and `44/vehicle_breakdown` not wired (`P36t`, `P25t` outbound on V3);
  `summary.json` (`FULL FAIL`, 4/18 cells ok, $2.31, cache read 89 %), `judge_batch.json`
  (`msgbatch_012HzJKr28ac5ZWL1D7yehRm`, 56 verdicts, collected), `progress.log`.
- `runs/full-fake/`: the offline rehearsal (seeds 42, 43).
- `runs/.fake-run-cache/<digest>/`: the gate's shared fake run (safe to delete; rebuilt in 14 s).
- `runs/cp2`, `runs/cp3`, `runs/golden-judge`: unchanged from CP3; the receipts point at them.
- `cost_report.md` (committed): regenerated at the end of `--full`.

## Acceptance status
- `time uv run python evals/run_evals.py --gate`: `GATE PASS`, 306 passed, 46.9 s with a cold
  fake-run cache and 32.2 s warm (hot laptop, otherwise idle). Receipts on the line: judge
  golden 12/12, demo $0.83, day 56.9 s, re-plan 13.3 s.
- `uv run --env-file .env python evals/run_evals.py --full`: kicked off in the background at
  18:08, cells done by 18:15, batch submitted 18:17:52 and collected 18:20:15, `FULL FAIL` for
  the reason above (baseline PASS on all seeds; breakdown not wired on 43 and 44).
- `uv run ruff check .`: clean. `pytest evals/repo` 134 passed (hook tests included).
- Reviewer: one pass on the whole CP4 range; verdict then "not done" (gate 86-97 s in its runs,
  speed-ups missing from the code, freeze inactive, hook gap on `git commit -a`). All
  must-fix and should-fix items fixed, one waived; docs/cp4-decisions.md "Reviewer findings".
- Not done: `/doctor` (interactive); B's hand-grading of the calibration notes (unchanged from
  CP3); the four unwired events; re-homing an outbound leg on a down van.

## What's next
1. `/kickoff cp5`: two timed dry runs of `make demo`, `docs/backup.mp4`, `docs/demo_script.md`
   (the `demo-narrator` subagent). No `src/c2r/` change is allowed; a viz fix goes through
   `src/c2r/viz/` only. Anything else needs a spec update, reviewer sign-off and a waiver in
   `.claude/freeze.json`.
2. Watch the day-run clock on camera: seed 43 took 88.9 s in the loop against the 90 s rule;
   the demo seed (42) took 56.9 s and 71.4 s on its two live runs.
3. After the event: wire `late_arrival` first (a `late_start_min` bump, the cheapest handler),
   then outbound re-homing for `vehicle_down`; each is a spec update. `make full` re-runs only
   the cells that are not `ok`; `make full-collect` finishes a batch that outlived the process.
4. `E28r` (seed 44) failed the judge; `runs/full/44/baseline/judge_scores.json` has the
   rationale. Nothing gates on it.
