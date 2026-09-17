# CP2 decisions

Read this before judging a live run or editing the orchestrator, the tools or the mediator
prompt. Each line is a decision made while building the mediator loop, with where it lives.

## What a live run looks like (seed 42, `make mediate`, Fable 5.1 at medium effort)
| Measure | Run of 2026-09-17 | Where it comes from |
|---|---|---|
| mean post-wait (min) | 70.21 -> 1.71 | `metrics.compute_metrics` after the closing pass |
| p90 post-wait (min) | 131 -> 6 | same |
| equity gap (min) | 32.14 -> 0.89 | same |
| riders flagged | 4 -> 1 (the stretcher rider, P30f) | `review_queue.json` |
| J | 1117.15 -> 128.6 | `moves.j_score` |
| bundles applied | 3 by the model (chained bundles) + 1 closing re-time | `bundles.json`, `ledger.jsonl` |
| model turns / tool calls | 7 / 15 | ledger |
| wall clock | 56.9 s (the three runs of the day: 88.6, 61.2, 56.9 s; see the prompt notes) | `metrics.json["elapsed_s"]` |
| cost | $0.56 | ledger `cost_usd`, handoff price table in `llm.PRICES` |
| cache-read share | 83 % overall; 92-98 % on every turn after the first | ledger `usage` |
| violations | 0 | `verify_after.json` |

The solver alone (`make solve`) reaches J 137.3 in 14 single moves; the mediator reaches 128.6 in
three chained bundles because a chain re-verified as a whole keeps the window re-timings that
the single-move loop only added at the end.

## Decisions
| Decision | Choice | Why |
|---|---|---|
| Eight tools, not nine | `get_state`, `generate_candidates`, `propose_to_unit`, `propose_to_broker`, `verify`, `apply_bundle`, `flag_for_review`, `finish` (`tools.TOOLS`). The handoff's `write_ledger` is gone. | Python writes every ledger entry itself (run start, each model turn, each tool call, run finish). The model's reasons travel in `apply_bundle.rationale` and `finish.summary`. A model cannot forget, skip or forge a ledger line. |
| Iteration = one model turn | `stop.max_iterations` (12) caps API calls; the ledger `iteration` is the turn index, run start is 0. | Cache share and cost are per API call; that is the unit the spec measures (I20 "from iteration 2"). |
| Two-turn protocol | Turn A: `propose_to_unit` + `propose_to_broker` + `verify` for one bundle in a single response. Turn B: `apply_bundle` with the hash. The apply result carries the delta and the next candidates. | Each turn costs 4-10 s of model time; three round trips per bundle would blow the 90 s budget. `apply_bundle` cannot share a turn with `verify` because the hash is not known until verify returns. |
| Chained bundle `C001` | `solver.chain_bundle` packs up to `max_moves_per_bundle` (6) greedy, party-accepted single moves into one bundle, re-applied from the start state so replay reproduces it; offered beside the top-k singles. | The CP1 loop needed 13 single steps on seed 42; a mediator turn must be able to move six things or the run needs 26 turns. The model still sees the singles and may prefer one. |
| `verify(bundle_id)` verifies the preview | The hash is bound to (bundle, current schedule version) in `Session.verified`; `apply_bundle` refuses a hash from another bundle or an older version, a bundle either party has not accepted since the last apply, and anything at `autonomy_level` 0. | C1/K2/K4: the model cannot apply what it has not verified, and cannot reuse yesterday's proof. Refusals are tool results with a reason, never exceptions, so the run continues. |
| K4 numeric claims | `claims.numeric_claims` extracts clock times and bare numbers from the model's prose (identifiers such as P31f or S12-B194 excluded); `claims.numbers_in` records every number a tool returned; the difference is logged as `unverified` in the model's ledger entry and shown on screen as `30 [unverified]`. The text is kept verbatim. | The judge (CP3) zeroes accuracy on numbers absent from the ledger; the mediator's own prose gets the same treatment now. On the first live run the model wrote "within 30 minutes" before any tool had returned the target; the targets are now in every `stop` block so the claim verifies. |
| Finish reuses the solver's closing pass | `solver.finish_run` (factored out of `solve`): honest windows, review queue, holds over 45 min, final verify. Model-flagged items come first; the deterministic queue adds subjects the model missed; only deterministic items hold a rider. | One definition of "done with the day" for both the solver and the mediator; `review_queue.json` is never empty when residue exists. |
| Offline fake mediator | `llm.FakeMediator` plays the protocol (lowest-J candidate, next on rejection, finish when told) with imitation cache usage; `--fake` on the CLI, `make mediate-fake`. | The gate runs the whole loop, the ledger and I16-I19 in 12 s without a key; the live run and I20 are `llm`-marked (`make test-live`). It is also the no-network demo fallback. |
| Cache breakpoints | Block A (prompt; the tools before it ride on the same breakpoint), block B (both policies + rules.yaml), block C (roster, manifest, fleet as compact JSON, per-zone travel summary), and a moving breakpoint on the latest user message. TTL 5 min. | Four breakpoints is the API maximum. The moving one lets the growing tool history read from cache; measured 91-100 % per turn after the first. Blocks A-C are built once and never mutated (H2). |
| Strict tools without numeric bounds | `k` is described as "1 to 6" and clamped in the handler. | The strict-tool grammar rejects `minimum`/`maximum` on integers (400 on the first live call). |
| Run directory | `runs/cp2` by default (git-ignored, stable for `make` and the timeline hook); `run_id` in every ledger entry; `--out` overrides. | The demo needs a fixed path; the ledger needs a unique id. |
| Timeline on every apply | `Session.on_apply` writes an interim `schedule_after.json` and re-renders `timeline.html`. | K3: the schedule is visible while the run is on camera, not only at the end. |

## Prompt (`prompts/mediator.v1.md`, block A, about 760 tokens)
Four laws (never compute a number; never apply without a clean verify on the current version;
take the hint and move on when a side rejects; queue rather than force), the two-turn protocol,
the decision policy (lowest J unless a note, caregiver window or equity reason says otherwise,
named in `rationale`), when to stop, and the tone. Two edits after live runs: the `subject` of a
flag is one id (the first run spent two turns on a sentence as the subject), and "do not ask for
a go-ahead; nobody answers" (the second run spent a turn waiting). The numbers above are from
the third run, on the prompt as committed (the ledger's `block_a` hash matches it).

## Reviewer findings (recorded, not all fixed)
- Fixed: `usage_summary` still counted the harness `run_finish` entry as a tool call after the
  event rename; `git_sha` now carries `-dirty` when the tree has uncommitted changes, so a ledger
  written before a commit says so; `finish` freezes the session (later tool calls in the same
  response are refused); K4 claim extraction now covers the model's tool-input prose
  (`rationale`, `summary`, draft messages), not only its free text; no new turn starts inside 15 s
  of `stop.max_wall_s` (a turn can take 30 s); I19 requires the most recent verify of the bundle
  and the applied state's hash to equal the verified preview; a forced-finish test at
  `max_iterations: 1`.
- Recorded for CP3: `numbers_in` is a run-wide bag, so a small integer the model invents
  ("6 vans") can match a schedule version or a target and count as verified. The judge should
  match an explanation's numbers against its own `ledger_refs` entries only and require a label
  match for one- and two-digit integers. Clock times the model copies from block C (the
  manifest) are not in any tool result and show as unverified; that is the rule working as
  written, and CP3 can add the subject's manifest rows to the ledger refs.
- Recorded: under the two-turn protocol 12 iterations is at most 6 applied bundles; the
  deterministic `R` review items are in `review_queue.json`, not in the ledger (the schedule
  replays, the queue does not).

## Not done at CP2
- `--replay` of a frozen ledger for a no-network demo; `--fake` is the offline fallback.
- Level-2 autonomy (cross-shift moves, extra vehicle hours) is not wired; the parties reject those
  bundles at level 1 as before.
- Perturbation events, explanations and the judge are CP3.
