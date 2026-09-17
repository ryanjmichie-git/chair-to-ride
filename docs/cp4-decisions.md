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
| second attempt (what the review saw) | 4 workers, 292-301 passed: 35-56 s in this session but 86-97 s in the reviewer's two runs. The speed-ups the docs credited (memoized `to_min`, cached `State` dicts, the fake run cached by digest) had **not** landed: the bash command that wrote them also held an `rm -rf` and was refused whole by `danger_guard`; only its second half was re-run, so the timings came from a lock-shared fake run built inside a worker on a cool laptop. The fake run's own clock (`elapsed_s`, asserted <= 60 s) was also measured while three other workers ran solvers: 61.6 s in the reviewer's first run | reviewer report; `git show 5a87c4c -- src/` |
| after the review fixes | 4 workers, 306 passed: 48.7 s cold (11.2 s serial build + 35.4 s pytest), 35.2 s warm on a cool laptop; **74.2 s cold** (15.6 s build + 56.3 s pytest) a few minutes later once the laptop had heated up under the repeated runs. The 86 hook tests each started a Python process (about 30 s of CPU) and were the critical path | `time uv run python evals/run_evals.py --gate`, three runs |
| final | **4 workers, 306 passed: 46.9 s with a cold fake-run cache (11.7 s serial build + 32.8 s pytest), 32.2 s warm, measured on the still-hot laptop** (`GATE PASS`), against the 60 s line and the Stop hook's 90 s subprocess timeout. The hook tests now run in-process (`runpy`, same stdin JSON, exit code and streams; one test still spawns the real interpreter), and the git-driven ones sit in their own module | `time uv run python evals/run_evals.py --gate` after the hook-runner change |

What made the difference, in order:
1. `pytest-xdist` (`-n 4 --dist loadscope`, `evals/run_evals.py WORKERS`). Four workers beat ten:
   the solver is CPU-bound and the laptop clocks down under all-core load.
2. One fake mediator run per session, cached on disk (`evals/fakerun.py`, used by
   `evals/conftest.py` and `run_evals._gate`): the run is a pure function of `src/c2r`, `config/`,
   the seed-42 day, `prompts/mediator.v1.md` and `pyproject.toml`, so it lives under
   `runs/.fake-run-cache/<digest of those>` and is rebuilt only when one of them changes. `--gate`
   builds it serially before pytest starts (so its `elapsed_s` is measured on an idle machine);
   a bare `pytest` builds it behind a lock file, a crashed build leaves a `FAILED` marker so no
   worker waits on it, and every worker works on its own copy.
3. `timeutil.to_min` memoized (`lru_cache`) and `State.patients` / `riders` / `broker_riders`
   cached per instance (`cached_property` on the frozen dataclass; `with_` makes a new instance).
   No behaviour change; the invariants and I18 replays pass unchanged.
4. `test_solver_is_deterministic` does one extra solve and compares its first bundle, `j_before`
   and `j_after` against the module's solve, instead of two extra solves compared with each other.
   Byte-for-byte determinism of a whole run stays with I18 (ledger replay) in `test_mediator`
   and `test_perturb`.
5. `evals/repo/test_hooks.py` drives each hook in-process with `runpy` (stdin JSON, argv,
   env, cwd, exit code and both streams exactly as the subprocess did) instead of a Python
   start-up per test; `test_phi_guard_fails_open_on_bad_stdin` still spawns the interpreter so
   the entry point is proven once. The git-driven K2 and freeze tests moved to
   `test_hooks_git.py` (the `repo` fixture to `evals/repo/conftest.py`) so loadscope can spread
   them. The repo suite went from 41 s to 22 s serial.

Variance to expect: the laptop (a 15 W part) clocks down under sustained load, so the same
gate measured 35 s and 56 s of pytest time twenty minutes apart before the hook change. The
final numbers above were taken hot; a cool machine is faster.

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
| A seed the handler cannot take | `perturb._vehicle_down` raises `NotImplementedError` when V3 carries an outbound leg after 13:40 (seed 43: `P36t`, seed 44: `P25t`). The cell is `not_wired` for that seed and the scenario reads `FAIL (not wired for seed 43,44)`, so `pass^k` fails honestly instead of the suite crashing or the seed being dropped | re-homing an outbound leg is the event work CP4 did not take on |
| Verdict | `FULL PASS` only when every wired scenario passes on every seed (`pass^k`) and the judge batch is collected | handoff section 9 |
| Offline rehearsal | `--full --fake` runs the same code with `FakeMediator`, `FakeWriter`, `FakeBatchWriter` into `runs/full-fake/` (never `runs/full/`, so a rehearsal cannot mark a live cell done); `evals/scenarios/test_suite.py` covers the runner in the gate | |

Live result of the kick-off: see "Live suite" below.

## Batch judge and cache TTL (`src/c2r/llm.py`, `judge.py`, `orchestrator.py`, `perturb.py`)
- `cost_usd(model, usage, batch=True)` halves every token price (`BATCH_DISCOUNT`).
- `AnthropicBatchWriter.submit / status / collect`: one `messages.batches.create` with the judge
  system prompt as a `cache_control: {ephemeral, ttl: "1h"}` block per request; results keyed by
  `custom_id` (`<run index>-<explanation id>`; only `[a-zA-Z0-9_-]` is allowed), never by position; `errored`, `expired`, `canceled`
  and a `refusal` come back as `data=None` and are scored `unscored` (needs human edit), as before.
- `judge.judge_batch` writes the batch id to `judge_batch.json` before polling, so a killed process
  or a wait past `max_wait_s` (3,600 s in the suite) is finished later by `judge_collect`; each run
  gets the same `judge_scores.json`, `judge_summary.json` (with `batch_id`), `judge.jsonl` and
  `metrics.json["usage_judge"]` as `judge_run` writes.
- `orchestrator.build_blocks(state, data_dir, cache_ttl)`: the ttl rides only in `cache_control`;
  block text and hashes are unchanged, so a day run and its re-plan still share the cache. The
  demo keeps the 5-minute default.
- `src/` diff: 346 changed lines in the batch-judge commit, 3 for the custom-id fix, and the
  review-fix commit (memoized `to_min`, cached `State` dicts, `PROMPT.name` in the judge ledger,
  the batch error text, the `judge_collect` status check); each commit under K2's 400.

## Code freeze
`.claude/freeze.json` (`active: true` from the checkpoint's last commit, `since: cp4`, frozen
`src/c2r/**`, allowed `src/c2r/viz/**`, `waivers: []`). `.claude/hooks/code_freeze.py` runs on
Edit|Write (the target path) and on Bash|PowerShell (`git commit`: the staged files, or the
working tree for `git add && git commit`, `-a`, `-am`, `--all`, `--include`, or a pathspec) and
denies a frozen path without a waiver naming the spec update and the reviewer. Tests in
`evals/repo/test_hooks_git.py`. Bash edits (`sed`, heredocs) to `src/c2r/` are not caught by the
edit hook; the commit-time check is the backstop. The file was committed inactive while the
review fixes (which touch `src/c2r`) landed, and switched on in the final commit.

## CLAUDE.md
The `/doctor` command is a Claude Code built-in that only Ryan can run interactively; this
session did the prune by hand: no line removed (each still prevents a mistake seen in CP0-CP3),
one Rules line added (the freeze) and one Lessons line (the refused-command incident below);
a Commands line for the new make targets was added and then dropped on the reviewer's point
that it is readable from the Makefile. 39 lines against the 60 cap (`evals/repo/test_claude_md.py`).

## `cost_report.md`
`evals/cost_report.py` sums every `ledger.jsonl`, `explain.jsonl`, `judge.jsonl` and
`calibration.jsonl` under `runs/` into tokens by type, cache-read share and dollars by model,
then one row per ledger (batch rows marked). Regenerated by `make cost-report` and at the end of
`--full`; never edited by hand (handoff section 10).

## Reviewer findings
One reviewer pass on the whole CP4 range (`git diff 3284b10..HEAD`). Verdict then: not done.
Fixed, tests first, all offline:
- The gate was 86-97 s in the reviewer's runs and the credited speed-ups were not in the code
  (see the gate table). Landed for real: `evals/fakerun.py` digest cache built serially by
  `--gate`, `lru_cache` on `to_min`, `cached_property` on `State`; hook tests split in two.
  Re-measured: 48.7 s cold, 35.2 s warm; a later hot-laptop run at 74.2 s cold led to the
  in-process hook runner, after which the hot laptop gives 46.9 s cold and 32.2 s warm.
- The fake run's 60 s clock was asserted on a run built under xdist contention; it is now built
  before pytest starts.
- `git commit -a` / `-am` / `--all` / `--include` / a pathspec bypassed the freeze hook (only the
  index was read); those read the working tree now, with a test per form.
- `--full-collect` on a batch still processing would have crashed in `results()`; `judge_collect`
  checks `status()` first and says "collect later".
- The judge receipt tied 12/12 to the prompt only; it now also carries the golden set's sha
  (`golden_explanations.json`), asserted against disk.
- The judge ledger hard-coded `judge.v1.md`; a `v2` bump would have failed the gate for good.
  `PROMPT.name` now.
- `none_stranded` treated a `will_call` trip left on the down van as fine; it counts now.
- A crashed shared build made waiters spin for 300 s; a `FAILED` marker fails them at once.
- The batch error text read `.type`/`.message` off the wrapper; it reads the nested error now.
- Doc numbers corrected (306 tests, per-commit `src/` lines, seeds 43 and 44 both unwired).
- CLAUDE.md: the make-targets line dropped; the freeze line kept.
- The live-suite table below was written after the review started and is committed with it,
  along with the regenerated `cost_report.md`.
Waived: a `/lesson` line for the batch `custom_id` pattern (the offline test asserts the
pattern; the lesson recorded instead is the refused-command one, which caused the false
claims in the docs).

## Live suite (kicked off 2026-09-17 18:08, finished 18:20; `runs/full/`)
| Cell | Result | Loop s | Cache read | Notes / judge pass | Dollars (mediator + notes + judge) | Where |
|---|---|---:|---:|---|---:|---|
| 42 baseline | ok, all five outcomes met | 71.4 | 86 % | 16 / 100 % | $1.21 | `runs/full/42/baseline/cell.json`, `judge_summary.json` |
| 42 vehicle_breakdown | ok, all four outcomes met (P15f, P29f re-homed, P16f queued) | 13.8 | 94 % | 4 / 100 % | $0.23 | `runs/full/42/vehicle_breakdown/` |
| 43 baseline | ok, all five outcomes met | 88.9 | 90 % | 19 / 100 % | $1.43 | `runs/full/43/baseline/` |
| 43 vehicle_breakdown | not wired for this seed: V3 carries outbound leg `P36t` after 13:40 | - | - | - | $0 | `cell.json` |
| 44 baseline | ok, all five outcomes met | 61.8 | 85 % | 17 / 94 % (`E28r` needs a human edit) | $1.20 | `runs/full/44/baseline/` |
| 44 vehicle_breakdown | not wired for this seed: V3 carries outbound leg `P25t` after 13:40 | - | - | - | $0 | `cell.json` |
| four unwired scenarios x 3 seeds | NOT WIRED, no calls | - | - | - | $0 | `cell.json` |
| **verdict** | **`FULL FAIL`: `baseline=PASS`, `vehicle_breakdown=FAIL (not wired for seed 43,44)`, four `NOT WIRED`; 4 of 18 cells ok** | | mean 89 % | 56 verdicts in one batch, 2 min 23 s from submit to results | **$2.31** | `runs/full/summary.json`, `progress.log` |

What the numbers say:
- The verdict is a fail and should be: `pass^k` needs every seed, and the breakdown handler
  cannot take a van that still has an outbound leg. Seed 42 (the demo seed) passes both wired
  scenarios. Re-homing an outbound leg is the first item of the post-freeze event work.
- Seed 43's day run took 88.9 s in the loop against the 90 s line (11 turns). The demo seed took
  71.4 s here and 56.9 s in `runs/cp2`; turn count is the model's, so the runtime outcome is not
  a safe margin on every seed.
- The 1-hour cache on the batched judge barely read: 3 % on seed 42's notes, 0 % elsewhere
  (`cost_report.md`, judge rows: 27,900 cache-write tokens against 1,860 read for 16 notes). The
  batch processed the requests side by side, so each wrote the prefix instead of reading it. The
  saving came from the batch discount: 56 verdicts for $1.75, $0.031 each, against $0.065 each for
  the 12 synchronous golden verdicts at CP3. Not worth a second attempt at demo time.
- The mediator's cache read 85-90 % on every day run and 94 % on the re-plan, as at CP2/CP3.
- The first batch submit was rejected: `custom_id` may only contain `[a-zA-Z0-9_-]` and the id
  carried a colon. Fixed (`judge._custom_id`), asserted offline, resubmitted; the cells were kept.
- Money this checkpoint: $2.31 for the live suite (the estimate was $5-8; two of six live cells
  did not run) plus $0 for the offline rehearsals. `cost_report.md` totals $5.68 across every
  ledger under `runs/` since CP2, of which $4.97 is Fable 5.1.
