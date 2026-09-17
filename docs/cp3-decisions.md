# CP3 decisions

Read this before touching the perturbation path, the explainer, the judge, or either of their
prompts. Each line is a decision made while building CP3, with where it lives. Money and timing
are from the artefacts named in the tables; nothing here was typed from memory.

## What the live re-plan looks like (seed 42, `make perturb`, Fable 5.1 at low effort)
Source run: `runs/cp2` (`20260917T181530Z-ba850d`, the CP2 live run). Event: V3 down at 13:40.

| Measure | Run of 2026-09-17 (`runs/cp3`, `20260917T190337Z-ba88be`) | Where it comes from |
|---|---|---|
| wall clock inside the loop | 13.3 s (first live run of the day: 33.2 s, see below) | `metrics.json["elapsed_s"]` |
| wall clock of the command | 21.4 s (`time` on the spec's verification command; Python start-up, state load, blocks, artefacts, timeline) | the shell |
| affected V3 trips | P16f, P15f, P29f (returns on V3 at or after 13:40) | `event.json["affected"]` |
| outcome | P15f re-homed to V4, P29f to V2 (bundle `I00-C001`); P16f held for the dispatcher (`R01`, `BROKER_POLICY`: a legal van scores J 140.6 against 134.9 for a hold); P30f stretcher (`R02`) as before | `bundles.json`, `review_queue.json` |
| model turns / tool calls / bundles | 2 / 6 / 1 | ledger, `metrics.json["usage"]` |
| J | 163.05 -> 134.9 | `moves.j_score` |
| riders flagged | 4 -> 2 | `review_queue.json` |
| mean post-wait (min) | 2.07 -> 1.81; p90 6 -> 6; equity gap 1.0 -> 0.89 | `metrics.compute_metrics` |
| vehicle minutes | 521 -> 558 (the two re-homed returns ride on V4 and V2) | same |
| cost | $0.07 | ledger `cost_usd` |
| cache-read share | 94 % (90 % on turn 1, 98 % on turn 2): blocks A-C are byte-identical to the day run's, so a demo that runs `mediate` then `perturb` reads them from cache | ledger `usage` |
| violations / unverified claims | 0 / 0 | `verify_after.json`, ledger |

The first live run took 33.2 s: turn 3 hit the 10 s client timeout, the retry took another 7 s,
and the model then spent a turn calling `finish`. Three changes, all in `perturb.py`: the
client timeout is 12 s with no retry (`TURN_TIMEOUT_S`, `retries=0`), no turn starts inside
15 s of the 30 s clock (`TURN_MARGIN_S`), and the harness ends the run itself once an apply
meets the stop rule (`stop_after_apply=True` in `orchestrator.run_session`), so the model's
own `finish` turn is not spent. Second run: 13.3 s, two turns.

## Explanations and the judge (live, 2026-09-17)
| Measure | Value | Where it comes from |
|---|---|---|
| notes written | 20: `runs/cp2` 16 (14 rider, 1 nurse, 1 dispatcher), `runs/cp3` 4 (2 rider, 2 dispatcher) | `explanations.json` in each run |
| explainer cost | $0.15 (cp2) + $0.04 (cp3), Sonnet 5 at medium effort, no caching | `metrics.json["usage_explain"]` |
| numbers outside the note's own refs | 0 of 20 notes (I16, `explain.check_numbers`) | `explanations.json` re-checked after the run |
| notes missing a new time | 0 of 20 (`explain.missing_times`; dispatcher notes are exempt) | same |
| reading grade | 2.0 to 4.6 (cp2), 2.3 to 3.9 (cp3); the rubric's cap is 8 | `explanation.reading_grade` (textstat Flesch-Kincaid) |
| judge on the golden set | agreement 12/12; mean scores accuracy 1.83, actionable 1.75, plain 1.75, tone 1.83, complete 1.17, safe 1.75 | `runs/golden-judge/judge_summary.json` |
| judge cost | $0.78 for the 12 golden calls (Fable 5.1, low, about 5,000 input tokens each). The 10 calibration calls of this session's pass were not ledgered; fixed the same day (`judge_calibration` books to `calibration.jsonl`, `--judge-only` prints both costs), so the next pass records them | `runs/golden-judge/judge.jsonl` |
| `--judge-only` wall clock | 188.5 s for 22 calls | the command's own summary line |
| judge on the calibration notes | 9 of 10 pass; C10 (the dispatcher note for the stretcher rider) fails on actionable 1, plain 1, complete 1: "Patient P30" is an id, and the note does not say where the crew reports | `runs/golden-judge/calibration_scores.json` |
| clinical teammate's grading | 0 of 10 graded; `human_pass: null` throughout | `evals/data/judge_calibration.json` |

## Decisions
| Decision | Choice | Why |
|---|---|---|
| A down vehicle is a fleet row, not a new rule | `vehicle_down` at `t` = fleet `status: down` + shift end `t`. H9 flags a down vehicle's stops after its shift end (`H9_SHIFT`), never its morning stops (`verify.h9_vehicle_inside_shift`). No schema or `ViolationCode` change. | The domain rule is "a down vehicle takes no stops after `t_down`"; the previous check flagged every stop and killed every candidate. |
| The clock lives in `State.now` and is enforced in `verify.py` | `now` (minutes since midnight, `None` for a full day). With `now` set: a chair start that changes when either the old or new start is before `now` is H3 ("already on the chair"); a served stop (ETA before `now`) that changes, or a trip whose baseline window opened before `now` that changes vehicle, window or status, is H9 (`h9_past_is_frozen`, code `H9_PAST`). | Every constraint lives in `verify.py`. 39 of the 80 first-pass candidates touched the past before the freeze existed; the solver drops frozen candidates the same way it drops infeasible ones, so no move generator changed. |
| The perturbed running state is the session's baseline | `perturb.event_state`: the day on disk + the source run's `schedule_after.json` (roster, manifest, chair moves booked into `moves_this_week`) + the event + the affected trips removed from the plan. Consent, H13 and the parties compare against the state at 13:40, not the morning. | The morning's changes are done and paid for; a re-plan that undid them would be a second move for the same patients. The unit's per-shift change budget therefore starts again at the event. |
| Same loop, same prompt, a tighter clock | `orchestrator.run_session` is the loop `run()` and `perturb.run()` share. The re-plan overrides `stop` with `max_wall_s: 30, max_iterations: 4` (`REPLAN_STOP`), effort low, turn timeout 12 s, no retry, 15 s margin, `stop_after_apply`. A failed model call (`llm.MediatorError`) halts the loop and the closing pass still runs. | One mediator, one ledger format, one review queue; the demo must always end with a verified schedule on camera. |
| The opening message carries the event and the delta | `perturb.run` puts the event, `now`, the affected trips and `claims.state_delta(original, state)` in the first user message, and the same facts in the `run_start` ledger line (`event`, `affected`, `source_run_id`, hashes of `source.schedule_after.json` and the event). | Blocks A-C stay byte-identical to the day run (cache); the delta rule from CP2 ("what changed since block C goes in the message"); the breakdown time is citable by an explanation (`L-1`). |
| Ledger refs are addresses, not copies | `L-n` = line n of the run's `ledger.jsonl` (1-based); `S-<id>` / `B-<id>` = that trip's or patient's row in `schedule_after.json` / `schedule_before.json` (trip rows carry their stops); `R-<item_id>` = a review item. `facts.resolve_refs` returns the referenced data with the model's proposals stripped from resolved ledger lines. I16 (`explain.check_numbers`) matches a note's numbers against its own refs only. | Closes CP2's "run-wide bag" gap: a number the writer invents cannot match a figure from another subject's line. No `LedgerEntry` schema change. |
| Python builds the facts card; the model only phrases it | `facts.facts_card(files, subject, audience)`: before/after times, the bundles and rationales that touched the subject, the event, the review item, the contact string, the refs. Sonnet 5 returns `{what_changed, why, contact}`; `explain.build` fills `new_times`, `ledger_refs`, `reading_grade` and validates `Explanation`. Explanation ids `E{nn}{r|n|d}`. | Numbers come from Python; the model never computes. The judge and the I16 check see the same card the writer saw. |
| Who gets a note | A rider note only when the rider is not in the review queue (K6); a nurse note for every patient whose chair moved; a dispatcher note per review item. Dispatcher notes are exempt from the "both new times" rule; a queued trip's stale window is not a ride, so `pickup_window` is filled only when the trip is scheduled on a vehicle. | A rider with an open item must hear from a person, not a note; the dispatcher's note is about the item, not a booked ride. |
| Judge = Fable 5.1 low + deterministic overrides | `judge.py`: rubric prompt, rationale before scores, strict JSON via `output_config.format` (dimensions as `enum [0,1,2]`). Then Python: a number outside the record's refs => accuracy 0; reading grade > 8 => plain <= 1; pass = total >= 10 and accuracy == 2, whatever the model said. A refusal or unparseable reply is `unscored` (all zeros, `needs_human_edit`), with no fallback model. `JudgeScore` is written with `model_dump(by_alias=True)`. | The model grades wording; the facts are checked by code. A fallback model would change the judge's identity mid-eval. |
| A single non-accuracy zero cannot fail a note | 5 x 2 + 0 = 10 meets the pass line. The five golden failures each lose at least three points across dimensions the model can see (a plain-language failure is also unclear about the place, and so on). | The rubric is the handoff's; the golden set has to be gradeable under it, so the failures are built to be unambiguous rather than the rubric bent. |
| Structured outputs everywhere | `llm.AnthropicWriter.complete(system, user, schema)` sends `output_config={"effort", "format": {"type": "json_schema"}}`, retries connection / rate / 5xx errors, re-asks once on bad JSON, and reports `stop_reason` (`invalid_json`, `refusal`, `max_tokens`). `PRICES["claude-sonnet-5"]` is $2 / $10 per million with the usual cache multipliers. | One JSON call per note and per verdict, no tool loop; the same writer serves the explainer and the judge. |
| Own ledgers for the explainer and the judge | `explain.jsonl` and `judge.jsonl` in the run directory, `metrics.json["usage_explain"]` / `["usage_judge"]`. | Dollars by model (handoff 9.E) without polluting the mediator's iteration and cache statistics. |
| Offline fakes | `FakeWriter` (templated prose from the card) and `FakeJudge` (all 2s; the overrides do the work) beside `FakeMediator`; `--fake` on every CLI. | The gate runs perturb, explain and judge without a key; the live path is `llm`-marked (`evals/invariants/test_cp3_live.py`). |
| Scope | Only `vehicle_down` is wired (`perturb.EVENTS`); an outbound leg on a down van raises `NotImplementedError` (none exist at 13:40 on seed 42); English only. | The spec names one event; CP4's `--full` suite needs the other four (`chair_down`, `late_arrival`, `add_on_patient`, `travel_slowdown`) and the registry is where they go. |
| The prompts are frozen | `prompts/explainer.v1.md` carries `eval_result: {judge_pass: 9/10, golden_pass: 7/7, unverified_numbers: 0/20, judged: 2026-09-17}`; `prompts/judge.v1.md` carries `{golden_agreement: 12/12, calibration_pass: 9/10, judged: 2026-09-17}`. `prompt_freeze` refuses edits; the next change is a `v2` file. | The numbers above were measured on these exact files. |
| Calibration is a human step | `evals/data/judge_calibration.json` ships with `human_pass: null` and `for_the_grader` summaries; `--judge-only` prints "0/10 graded" until B fills it; the judge gates nothing until CP4. | The spec's 8/10 agreement is between the judge and a person; there is no person in this session. |
| Money spent this checkpoint | Perturb: $0.36 (first run, medium effort defaults) + $0.07. Explain: $0.03 (cp3 test run) + $0.04 + $0.15. Judge: $0.78 golden + the 10 calibration calls (not ledgered; about $0.65 at the golden per-call average) + one model ping. The live test module adds one perturb, four notes and their verdicts when run. About $2.20 in all before the live test, against the $4 line in the plan. | Recorded per the "spending money" rule. |
| Gate time | `make gate`: 262 passed, 94.5 s, GATE PASS (the same set took 108 s with other work running beside it). Two CP2 tests that do not need the chained bundle (`test_autonomy_zero_never_applies`, `test_the_harness_forces_finish_at_the_iteration_cap`) now run with `max_moves_per_bundle: 1`, saving about 9 s; the shared fake mediator run is already one per session. | The Stop hook's subprocess timeout is 90 s, and a timeout skips the gate with a notice instead of blocking, so at 94.5 s the hook no longer guards a stop. Raising that timeout to 110 s (inside the 120 s hook budget in `settings.json`) was attempted and refused by the session's permission mode, so it is the user's call. The remaining time is the CP1 solver (a full solve and two short ones, 21 s), the shared fake run (15 s), the tools protocol round (9 s) and 36 hook tests that each spawn a process; CP4 owns the 60 s target. |

## Reviewer findings
(filled after the CP3 review)

## Not done at CP3
- The other four events; `--replay` of a frozen ledger for a no-network demo (`--fake` remains
  the fallback).
- B's hand-grading of the 10 calibration notes (`evals/data/judge_calibration.json`,
  `human_pass`), and the rubric edit if agreement lands under 8/10.
- Judge verdicts on the live runs' own notes are produced by `make judge`; only the golden set
  and the calibration file were judged live this session.
