# Session handoff

Updated 2026-09-17 at the end of CP3 (perturb, explain, judge). Start a fresh session from here.

## Built this session
CP3 landed in seven `cp3:` commits, each under 400 changed `src/` lines (details in
docs/cp3-decisions.md):

- `src/c2r/state.py`: `State.now` (minutes since midnight when a re-plan runs; `None` for a day).
- `src/c2r/verify.py`: a down vehicle keeps its stops before its shift end (`t_down`) and may
  take none after it (`H9_SHIFT`); with `now` set, a started chair cannot move (H3) and served
  stops and opened windows cannot change (`h9_past_is_frozen`, code `H9_PAST`).
- `src/c2r/orchestrator.py`: `run_session` (the loop) split from `run` (the full day);
  `margin_s`, `stop_after_apply`, and a failed model call halts the loop instead of raising.
- `src/c2r/perturb.py`: `load_event`, `event_state` (day on disk + the source run's
  `schedule_after.json` + the event; pure, replayable), `EVENTS` registry (`vehicle_down` only),
  `run` with a 30 s / 4-turn clock, effort low, 12 s turn timeout, no retry, 15 s margin.
  `python -m c2r.perturb --event vehicle_down --at 13:40 [--run runs/cp2] [--out runs/cp3] [--fake]`.
- `src/c2r/facts.py`: facts cards per subject and audience; refs `L-n`, `S-id`, `B-id`, `R-item`.
- `src/c2r/explain.py`: Sonnet 5 phrases the card; Python fills times, refs, reading grade;
  I16 per record (`check_numbers`), the two-times rule (`missing_times`), K6 (no rider note
  while queued). `python -m c2r.explain runs/cp2 [--fake]`.
- `src/c2r/judge.py`: Fable 5.1 low, strict JSON, six dimensions 0-2; Python overrides
  (invented number => accuracy 0, grade > 8 => plain <= 1, pass = total >= 10 and accuracy 2);
  golden and calibration passes. `python -m c2r.judge runs/cp2 [--fake]`, `--golden`.
- `src/c2r/llm.py`: `AnthropicWriter` (one structured-output call, retries, JSON re-ask),
  `Completion`, `MediatorError`, `FakeWriter`, `FakeJudge`, Sonnet 5 prices.
- `src/c2r/viz/timeline.py`: the heading names the event when a run has `event.json`.
- `prompts/explainer.v1.md`, `prompts/judge.v1.md`: both carry a one-line `eval_result` from
  the live passes and are frozen; the next edit is a `v2` file.
- `evals/data/golden_explanations.json` (12: 7 pass, 5 fail one bucket each),
  `evals/data/judge_calibration.json` (10 live notes, `human_pass: null` for B).
- `evals/invariants/`: `conftest.py` (one shared fake mediator run per session),
  `test_perturb.py`, `test_explain.py`, `test_judge.py`, `test_cp3_live.py` (`llm`), additions to
  `test_verify.py`. `evals/repo/test_prompts.py` (frontmatter and PHI contract).
  `evals/run_evals.py --judge-only`.
- `Makefile`: `perturb`, `perturb-fake`, `explain`, `judge`, `judge-only`; `demo` = `mediate`
  then `perturb`. `docs/llms.txt`, `docs/cp3-decisions.md`, `specs/INDEX.md` (CP2 done, CP3
  active).

## Decisions made (details in docs/cp3-decisions.md)
1. Event semantics live in `verify.py`: down = fleet `status: down` + shift end `t`; H9 flags
   only stops after `t_down`. The clock (`State.now`) freezes the past under H3 and H9.
2. The perturbed running state at 13:40 is the session's baseline; the morning's chair moves
   are booked into `moves_this_week`, so the change budget starts again at the event.
3. Same loop and prompt as CP2 (`run_session`); blocks A-C byte-identical to the day run, so a
   `mediate` then `perturb` demo reads them from cache (94 % on the live run).
4. The harness ends the re-plan itself once an apply meets the stop rule (`stop_after_apply`);
   the first live run spent 33.2 s on a timeout, a retry and a `finish` turn, the second 13.3 s.
5. Ledger refs are addresses (`L-n`, `S-id`, `B-id`, `R-item`); I16 matches a note's numbers
   against its own refs only.
6. Python builds the facts card and fills every number; the model phrases. Dispatcher notes are
   exempt from the two-times rule; a rider in the queue gets no note.
7. Judge overrides in code; a refusal is `unscored` (needs a human edit), no fallback model;
   a single non-accuracy zero cannot fail a note, so the golden failures lose >= 3 points.
8. Only `vehicle_down`; an outbound leg on a down van raises `NotImplementedError`; the other
   four events are CP4's, through `perturb.EVENTS`.
9. Calibration is B's: `human_pass: null` until graded; the judge gates nothing until CP4.
10. Money: about $2.20 before the live test module, about $2.85 after it, against the $4 line.

## Artifacts (git-ignored; the Makefile regenerates them)
- `runs/cp3/`: the live re-plan (V3 down at 13:40 against `runs/cp2`): `event.json`,
  ledger, bundles, review queue, schedules, `verify_after.json`, `metrics.json` (with
  `usage` and `usage_explain`), `explanations.json`, `explain.jsonl`, timeline.
- `runs/cp2/`: the CP2 live run plus its 16 explanations (`explanations.json`, `explain.jsonl`).
- `runs/cp3-fake/`: the offline re-plan (`make perturb-fake`).
- `runs/golden-judge/`: `judge_scores.json`, `judge_summary.json` (12/12), `judge.jsonl`,
  `calibration_scores.json` (9/10 pass; C10 fails).
- Live re-plan: 13.3 s in the loop, 21.4 s for the command, 2 turns, 1 bundle (P15f -> V4,
  P29f -> V2), P16f held (`R01`), P30f stretcher (`R02`), J 163.05 -> 134.9, $0.07, 0 violations.

## Acceptance status
- `time uv run --env-file .env python -m c2r.perturb --event vehicle_down --at 13:40`:
  `elapsed_s` 13.3, real 21.4 s, 0 violations, no V3 stop after 13:40, every affected trip
  re-homed or queued.
- `uv run --env-file .env python evals/run_evals.py --judge-only`: golden agreement 12/12,
  22 calls, golden cost $0.78, 188.5 s, `JUDGE PASS`; calibration 0/10 graded by B. Run before
  `judge_calibration` booked its calls (reviewer M1, waived: a re-run costs about $1.45, over
  the $4 line; the prompt hash in `runs/golden-judge/judge.jsonl` matches HEAD and the booking
  path has an offline test). `make judge-only` refreshes the artefacts.
- `uv run --env-file .env python -m pytest evals/invariants/test_cp3_live.py -k "not golden"`:
  2 passed in 66.8 s: the re-plan fixture 25.5 s including artefacts with `elapsed_s` under 30,
  explain + judge 39.9 s, every live note passed I16 and the two-times rule, at most one
  judge failure among them (the assertion). The golden test was deselected (see below).
- `uv run python -m pytest evals/repo evals/invariants/test_judge.py evals/invariants/test_explain.py -q`:
  138 passed. `uv run ruff check .`: clean.
- `make gate`: 271 passed, GATE PASS, 102.1 s after the review fixes (94.5 s before them, with
  nine fewer tests; run-to-run noise is about 5 s). Over the Stop hook's 90 s subprocess timeout: a
  timeout skips the gate with a notice instead of blocking, so the hook does not guard a stop
  right now. Raising the timeout in `.claude/hooks/eval_gate.py` to 110 s was refused by the
  session's permission mode. Ryan accepted the gap on 2026-09-17 until CP4 brings the gate
  under 60 s; do not raise it again before then.
- Not done: B's hand-grading of the 10 calibration notes; agreement is reported by
  `--judge-only` once `human_pass` is filled. The golden test in `test_cp3_live.py` was not run
  live (its function, `judge.judge_golden`, is what `--judge-only` ran: 12/12).
- Reviewer: one pass. Six should-fix items fixed with tests in the seventh commit (verify no
  longer pins a queued trip's stale window; a stop at exactly `t_down` is flagged; bookkeeping
  numbers stripped from refs; contact from the card; two-times and contact checks in the judge;
  a failed-call test). The rest waived with reasons in docs/cp3-decisions.md.

## What's next
1. B's grading does not block CP4 (the judge gates nothing until then). Send B
   `docs/calibration_sheet.md` (the ten notes with a Pass/Fail column, written for a
   non-technical reader); copy the verdicts into `human_pass` / `human_notes` in
   `evals/data/judge_calibration.json`; run `make judge-only`. Under 8/10 agreement, write
   `prompts/judge.v2.md` (v1 is frozen) and re-run.
2. `/kickoff cp4`: the other four events in `perturb.EVENTS` (`chair_down`, `late_arrival`,
   `add_on_patient`, `travel_slowdown`) for the `--full` suite (5 scenarios x 3 seeds); the
   gate back under 60 s (the fake mediator run is shared already; the chained-bundle greedy
   pass inside `generate_candidates` costs about 5 s per call and is the lever); code freeze
   except `viz/`.
3. Demo path: `make demo` runs `mediate` then `perturb`; `make explain` and `make judge` on both
   runs afterwards; `make timeline` still points at `runs/cp1` (run
   `python -m c2r.viz.timeline runs/cp3` for the re-plan).
4. Watch the re-plan clock on camera: 13.3 s with two turns; a timed-out turn costs 12 s and
   the margin ends the run at 15 s, so a run can finish forced but never late.
