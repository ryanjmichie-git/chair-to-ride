---
name: domain-rules
description: Use when editing solver, verify, parties, rules.yaml, or any spec that names a constraint
allowed-tools:
  - Read
---

# Domain rules (verbatim from handoff §4/§6)

## Hard constraints (checked by `verify()`, never by the model)
H1 No chair hosts two overlapping sessions; turnover ≥ `turnover_min` between them.
H2 `rx_duration` and `rx_days` are immutable. Sessions are never shortened, split, or moved to another day.
H3 `clinically_fixed` patients keep their start time exactly.
H4 `consent_to_move = false` patients keep their start time (they may still get a better ride).
H5 Put-on load: ≤ `stagger_cohort_size` sessions start in any `stagger_step_min` bin per shift.
H6 A return pickup window opens no earlier than `ready_time`.
H7 A pickup window's midpoint is within ±60 min of the rider's requested time (ADA negotiation bound) — else the trip is queued, not scheduled.
H8 Vehicle capacity by mobility class is never exceeded at any stop; stretcher trips are always queued for human assignment.
H9 Route feasibility: `eta_next ≥ eta_prev + dwell + travel(prev,next)`; vehicles operate only inside their shift; a down vehicle takes no stops after `t_down`.
H10 Ride time per rider ≤ `max_ride_min` (60) and ≤ 2 × direct travel.
H11 No stranding: every "from" leg is either scheduled or in the review queue with a `hold_for_will_call` action (mirrors no-strand policy).
H12 Arrival for the "to" leg lands in `[start − 30, start]`; never after start.
H13 Equity budget: `moves_this_week ≤ 1` per patient.

## Immovables
Prescription days; session duration; MD-fixed start times; stretcher assignments; anything the broker policy marks non-negotiable (e.g., no pickups before 06:30 — set in `broker_policy.md`).

## Soft objective (weights in `rules.yaml`, defaults shown)
`J = 1.0·Σ post_wait + 0.3·Σ early_wait + 8·(#chair changes) + 20·(#consent-flag moves) + 0.05·(vehicle minutes) + 15·(#review items)` — minimize. Ties broken toward fewer touched patients. The model may argue for a *different* bundle than the lowest-`J` one, but must say why in the ledger.

## Autonomy slider (config `autonomy_level`, default 1 for the demo)
| Level | Agent may do alone | Must queue for a human |
|---|---|---|
| 0 — propose | Nothing is applied; outputs a proposal pack | Everything |
| 1 — bounded (demo) | Chair shifts ≤ 30 min inside the same shift for `consent_to_move` patients; pickup windows inside ADA ±60 and after ready; vehicle reassignment and pairing within capacity; ≤ 1 move per patient per week | Any `consent_to_move=false` or `clinically_fixed` patient; stretcher trips; anything outside ±60; extra vehicle hours; will-call holds; any bundle the unit or broker party rejects twice |
| 2 — trusted | Level 1 + cross-shift moves for consenting patients + extra vehicle-hour requests | Fixed patients, stretcher, denials |

## Glossary
- **Put-on / take-off** — connecting/disconnecting the patient; staff-limited, hence **stagger**.
- **Turnover** — clean and set up a chair between patients.
- **Ready time** — session end + recovery buffer (site hemostasis, post vitals, weigh-out).
- **Standing order** — broker's recurring booking for dialysis days.
- **Will-call** — return trip requested when the patient is actually done.
- **Pickup window** — the 30-min band the vehicle must arrive in (on-time = inside it).
- **Negotiation window** — the ±60-min band in which the broker may legally shift the requested time.
- **Ride time** — minutes on board; capped for comparability to fixed-route transit.
- **No-strand** — a rider whose return cannot be scheduled must still get home.
- **Mobility class** — ambulatory / assist / wheelchair / stretcher; drives vehicle capacity and loading dwell.
