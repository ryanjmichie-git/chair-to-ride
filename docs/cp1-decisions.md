# CP1 decisions

Read this before judging the "after" number or editing the solver. Each line is a decision made
while building the solver and verifier, with where it lives in code.

## What the numbers mean (seed 42, `make solve`)
| Metric | Before | After | Where it comes from |
|---|---|---|---|
| mean post-wait (min) | 70.21 | 3.38 | `metrics.compute_metrics`, pickup minus actual ready |
| p90 post-wait (min) | 131 | 21 | same |
| equity gap (min) | 32.14 | 6.28 | wheelchair mean minus ambulatory mean |
| riders flagged | 4 | 2 | queued returns: the stretcher trip, and P31f (see below) |
| vehicle minutes | 3434 | 3307 | first stop to last stop per van |
| hard-constraint violations | 0 | 0 | `verify.verify`, H1-H13 |
| J | 1262.7 | 297.35 | `moves.j_score`, weights from `config/rules.yaml` |

Fourteen bundles were applied: twelve vehicle reassignments (two with the window re-timed to
where the van arrives), one pairing of the two S1 wheelchair riders on the lift van V5, and one
closing window re-timing. No chair shift survived the search on this seed: with five vans in
their openings, the ride side alone reaches the target, and every chair move costs 8 J for less
than that in wait. Chair-shift bundles are still generated and offered (`moves._moves`), so the
mediator at CP2 can pick one and say why. Every applied bundle is in `runs/cp1/bundles.json`
with the J before and after it and a unique id (`S<step>-B<n>`, `W<n>` for closing re-timings,
`H<n>` for holds).

P31f (S3, ready 20:35) stays queued with a `BROKER_POLICY` item, not `NO_FEASIBLE_WINDOW`: a
legal, accepted van exists (`S14-B194`), but it scores J 297.05 against 297.35 for the hold,
under the 2 percent stop rule. The reason is that `metrics.vehicle_min` counts a van's span from
first stop to last stop, so an evening return on a van idle since 15:35 costs five idle hours.
That is CP0's metric definition and B's weight; a candidate fix for B is to count on-task
minutes instead. The queue item says so and names the dispatcher.

## Decisions
| Decision | Choice | Why |
|---|---|---|
| Which vans a shift's returns may use | Every van the baseline already sends for that shift's riders, either leg (`routing.committed_vans`); on seed 42 that is all five | `fleet.json` says all five vans are on shift and every one of them already carries this unit's outbound trips. CP0's "one van per shift for returns" was a calibration assumption for the *before* state, not data. Under one van per shift the S1 van cannot physically serve eight riders inside their negotiation bands, so the target was unreachable and the queue rule swallowed most riders. A van outside the pool is an extra-capacity ask the broker rejects at autonomy 1 (`parties/broker.py`). |
| Will-call riders' request time | Their actual ready time from the roster, in verify (`requested_times`), the broker party and the solver; a return with no standing window is a will-call whatever its status (`verify.is_will_call`) | A will-call rider has no request until they are done; the baseline's `requested_time` on such a trip is the time they called, which for three S3 riders is after the vans' shift. Standing orders keep the baseline request; `verify.requested_times` and the broker read the anchor from the baseline, never the candidate. |
| Ready time for H6 vs for planning | H6 uses scheduled ready (start + rx + recovery); the solver plans against actual ready (scheduled + `late_start_min` + `runover_min`) | Keeps CP0's verifier definition; post-wait is measured against actual ready in `metrics.py`, and the roster carries the day's lateness as data. |
| Sub-codes | `H9_SHIFT`, `H9_ROUTE`, `BROKER_EARLIEST` report as `H9` | The VerifyResult schema only allows H1-H13. |
| A window the van cannot keep | A bundle's touched returns get their window re-timed to where the van will actually be (`moves._window_fixes`), inside the ADA band; a closing pass (`solver._retime_stale_windows`) does the same for riders whose pickup drifted because a batch-mate moved | The broker rejects a bundle whose van reaches the door more than `driver_wait_min` after the window closes, so an honest window is the only way a bundle passes. |
| Riders still over 45 min after the loop | Queued with `NO_FEASIBLE_WINDOW` and a hold-for-will-call action, removed from the plan, and written to `bundles.json` as an `H<n>` hold bundle; the solver prints the metrics before any hold | The handoff's stop rule. `riders_flagged` and the "before holding anyone" line show it; the mean is not allowed to hide them. On seed 42 no rider is held. |
| Diff size | CP1 landed as eight commits, each under 400 changed lines in `src/` | K2 in the PR checklist. A pre-commit check for K2 does not exist yet; adding one is a decision for the repo owner. |
| `ride_checks.py` | Renamed to `verify.py` with `git mv`, then extended | Content preserved; the rename commit is separate so the verifier diff reads clean. |
| Search | Greedy: the best bundle both parties accept, until J improves by less than `stop.min_improvement_pct`, the targets are met with every non-stretcher return scheduled, `stop.max_wall_s`, or `stop.max_iterations x max_moves_per_bundle` single-move steps | The mediator (CP2) replaces this loop and applies up to `max_moves_per_bundle` moves per round; `generate_candidates` is the API it will call. |

## Not done at CP1
- `swap_chairs` is accepted by `apply` but never generated; chair shifts covered every improvement the search found.
- `request_extra_capacity` is never generated; the broker's rejection of an uncommitted van is turned into the ask in the review queue instead.
- The after-state is for seed 42 only; seed 43 is not gated.
