# CP4 decisions

Read this before touching the eval gate, the `--full` suite, or anything under `src/c2r/`
(frozen since this checkpoint). Each line is a decision made while building CP4, with where it
lives. Every number is from a command run on 2026-09-17 on Ryan's laptop (13th-gen Core i7,
10 cores) and named in the tables; nothing here was typed from memory.

## The gate (`uv run python evals/run_evals.py --gate`)
| Measure | Value | Where it comes from |
|---|---|---|
| CP3 close-out | 271 passed, 95-102 s, serial | `docs/cp3-decisions.md`; re-measured 95.1 s at the start of CP4 |
| slowest pieces, serial | shared fake mediator run 13.8 s; `test_tools` protocol round 9.2 s; `test_solver_is_deterministic` 9.1 s (two extra solves); `test_invariants` full solve 8.6 s; about 60 hook subprocess tests 20 s | `pytest --durations=40` |
| a one-iteration solve, profiled | 9.86 s: 2,044 `moves.apply` calls, each rebuilding the manifest (6.1 s in `routing.build_manifest`); 1.8 million `to_min` calls (1.1 s); 214,000 rebuilds of `State.patients` (0.9 s with `patient_of`) | `cProfile` on `solve(short)` |
| first parallel attempt | 10 xdist workers, loadscope: 46 s with 271 tests; 68-77 s once the CP4 tests were added, because five workers each built their own fake run and ten solver processes throttled the laptop's all-core clock (the `test_tools` fixture took 28 s under load against 10 s alone) | `pytest -n 10 --durations` |
| final | **4 workers, 292 passed: 35.6 s with a cold fake-run cache, 38.8 s warm** (`GATE PASS`), against the 60 s line and the Stop hook's 90 s subprocess timeout | `time uv run python evals/run_evals.py --gate` |

What made the difference, in order:
1. `pytest-xdist` (`-n 4 --dist loadscope`, `evals/run_evals.py WORKERS`). Four workers beat ten:
   the solver is CPU-bound and the laptop clocks down under all-core load.
2. One fake mediator run per session, shared across workers and cached on disk
   (`evals/conftest.py`): the run is a pure function of `src/c2r`, `config/`, the seed-42 day and
   `prompts/mediator.v1.md`, so it lives under `runs/.fake-run-cache/<digest of those>` and is
   rebuilt only when one of them changes. Under xdist the first worker to take a lock file builds
   it; the others wait; every worker then works on its own copy, so no module's writes reach another.
3. `timeutil.to_min` memoized (`lru_cache`) and `State.patients` / `riders` / `broker_riders`
   cached per instance (`cached_property` on the frozen dataclass; `with_` makes a new instance).
   No behaviour change; the invariants and I18 replays pass unchanged.
4. `test_solver_is_deterministic` does one extra solve and compares its first bundle, `j_before`
   and `j_after` against the module's solve, instead of two extra solves compared with each other.
   Byte-for-byte determinism of a whole run stays with I18 (ledger replay) in `test_mediator`
   and `test_perturb`.

## The five gate criteria (spec DoD) and where each is checked
| Criterion | Check | Where |
|---|---|---|
| invariants 100 % | pytest exit 0 over `evals/repo`, `evals/data`, `evals/invariants`, `evals/scenarios` | `run_evals._gate` |
| baseline scenario within golden tolerance | the fake run's after-metrics within 15 % (floor 1 minute) of `evals/golden/baseline.json`, the before-metrics equal, 0 violations; beating golden on wait minutes by more than 15 % fails with "re-golden review" (handoff 9.B); the 9.B outcomes (mean <= 25, p90 <= 45, >= 60 % wait removed, queue <= 15 %, runtime <= 90 s) asserted too | `evals/scenarios/test_baseline.py`; golden written by `--golden-baseline` (mean 1.71, p90 6.0, 97 % of wait minutes removed, queue share 1/18) |
| judge pass rate >= 90 % on the golden set | agreement >= 11/12 in `evals/golden/receipts.json`, **and** the receipt's judge prompt hash equals the sha of `prompts/judge.v1.md` on disk, so a prompt change without a live re-judge fails the gate | `evals/scenarios/test_receipts.py`; receipts written by `--record` from `runs/golden-judge` (12/12, `sha256:fceb9de7...`) and refreshed by `--judge-only` |
| cost <= $4 per run | the demo's day run plus re-plan, from `runs/cp2` and `runs/cp3` `metrics.json`: $0.72 + $0.11 = $0.83 | same receipts |
| runtime <= 90 s | day run `elapsed_s` 56.9 <= 90; re-plan 13.3 <= 30 | same receipts |

The gate cannot call the API in under 60 s, so the judge, cost and runtime criteria are receipts
copied by Python from the last live artefacts, with the prompt hash as the link back to what was
measured. `--record` is the only writer of `receipts.json`; the summary line prints them.

## `--full`
| Decision | Choice | Why |
|---|---|---|
| Scope | **Wired scenarios only**: `baseline` and `vehicle_breakdown` on seeds 42, 43, 44. The other four section-9.B rows (`chair_outage`, `late_patient`, `over_capacity_day`, `travel_slowdown`) are scenario files with `wired: false` and the reason, reported `NOT WIRED`, no calls. | Ryan's choice on 2026-09-17 after exploration: no move type changes a patient's chair and verify has no chair-availability check; no free patient/rider/trip ids in the schemas and H2 forbids adding a patient; scaling the travel matrix makes H9 flag stops already made before the event; `late_arrival` alone would be a small handler. All four need solver/verify work under a spec update, which CP4 freezes. |
| Layout | one cell per seed x scenario under `runs/full/<seed>/<scenario>/` with `cell.json` (status, checks, dollars); `progress.log`; `summary.json`; `judge_batch.json` | resumable: a cell with `status: ok` is skipped; a saved batch id is collected by `--full-collect` |
| Models | baseline = `orchestrator.run` live (Fable 5.1, medium, `cache_ttl="1h"`), notes by Sonnet 5; `vehicle_breakdown` = `perturb.run` against that seed's baseline cell (Fable 5.1 low, 12 s turn timeout, no retry, 1-h cache); every note judged in **one Message Batch** (Fable 5.1 low, half price, 1-h cached system prompt) | handoff section 5: 1-h cache for suites and batches, never a demo gate on the Batch API |
| Required outcomes | computed from the cell's own files (`metrics.json`, `schedule_after.json`, `event.json`): baseline mean <= 25, p90 <= 45, >= 60 % wait removed, queue <= 15 %, runtime <= 90 s; breakdown none stranded (every affected trip re-homed off the down van or queued), 0 violations, re-plan <= 30 s, S2 riders' mean post-wait <= 35 | handoff 9.B |
| A seed the handler cannot take | `perturb._vehicle_down` raises `NotImplementedError` when V3 carries an outbound leg after 13:40 (seed 43: `P36t`). The cell is `not_wired` for that seed and the scenario reads `FAIL (not wired for seed 43)`, so `pass^k` fails honestly instead of the suite crashing or the seed being dropped | re-homing an outbound leg is the event work CP4 did not take on |
| Verdict | `FULL PASS` only when every wired scenario passes on every seed (`pass^k`) and the judge batch is collected | handoff section 9 |
| Offline rehearsal | `--full --fake` runs the same code with `FakeMediator`, `FakeWriter`, `FakeBatchWriter` into `runs/full-fake/` (never `runs/full/`, so a rehearsal cannot mark a live cell done); `evals/scenarios/test_suite.py` covers the runner in the gate | |

Live result of the kick-off: see "Live suite" below.

## Batch judge and cache TTL (`src/c2r/llm.py`, `judge.py`, `orchestrator.py`, `perturb.py`)
- `cost_usd(model, usage, batch=True)` halves every token price (`BATCH_DISCOUNT`).
- `AnthropicBatchWriter.submit / status / collect`: one `messages.batches.create` with the judge
  system prompt as a `cache_control: {ephemeral, ttl: "1h"}` block per request; results keyed by
  `custom_id` (`<run index>:<explanation id>`), never by position; `errored`, `expired`, `canceled`
  and a `refusal` come back as `data=None` and are scored `unscored` (needs human edit), as before.
- `judge.judge_batch` writes the batch id to `judge_batch.json` before polling, so a killed process
  or a wait past `max_wait_s` (3,600 s in the suite) is finished later by `judge_collect`; each run
  gets the same `judge_scores.json`, `judge_summary.json` (with `batch_id`), `judge.jsonl` and
  `metrics.json["usage_judge"]` as `judge_run` writes.
- `orchestrator.build_blocks(state, data_dir, cache_ttl)`: the ttl rides only in `cache_control`;
  block text and hashes are unchanged, so a day run and its re-plan still share the cache. The
  demo keeps the 5-minute default.
- `src/` diff for this work: 361 changed lines in one commit (K2 <= 400).

## Code freeze
`.claude/freeze.json` (`active: true`, `since: cp4`, frozen `src/c2r/**`, allowed `src/c2r/viz/**`,
`waivers: []`). `.claude/hooks/code_freeze.py` runs on Edit|Write (the target path) and on
Bash|PowerShell (`git commit`: the staged files, or the working tree after `git add`) and denies
a frozen path without a waiver naming the spec update and the reviewer. Tests in
`evals/repo/test_hooks.py`. Bash edits (`sed`, heredocs) to `src/c2r/` are not caught by the
edit hook; the commit-time check is the backstop.

## CLAUDE.md
The `/doctor` command is a Claude Code built-in that only Ryan can run interactively; this
session did the prune by hand: no line removed (each still prevents a mistake seen in CP0-CP3),
one Commands line added (`make full` / `full-collect` / `cost-report`) and one Rules line (the
freeze). 39 lines against the 60 cap (`evals/repo/test_claude_md.py`).

## `cost_report.md`
`evals/cost_report.py` sums every `ledger.jsonl`, `explain.jsonl`, `judge.jsonl` and
`calibration.jsonl` under `runs/` into tokens by type, cache-read share and dollars by model,
then one row per ledger (batch rows marked). Regenerated by `make cost-report` and at the end of
`--full`; never edited by hand (handoff section 10).

## Live suite
Filled from `runs/full/summary.json`, `runs/full/progress.log` and `cost_report.md` when the
kick-off finished; see the table at the end of this file.
