# Chair-to-Ride — Build Day Handoff

**For:** a fresh Claude Code session that will scaffold `chair-to-ride/` (kickoff prompt, CLAUDE.md, subagents, hooks, specs, evals) from this document.
**Event:** Claude Build Day for Healthcare, NYC, Sep 17 2026. Track: Breakthrough. Demo: 3:00 on camera.
**Written:** Sep 17 2026. All Anthropic product facts below were checked against live docs today; URLs in §15.
**Data rule:** synthetic only. No real people, no PHI, fictional unit, fictional addresses on a synthetic grid.

---

## 1. Pitch + tagline

**Chair-to-Ride** — *the chair schedule and the ride schedule finally talk to each other.*

An agent re-times a dialysis unit's chair schedule against the paratransit/NEMT manifest so patients stop waiting an hour for the ride home. It negotiates both sides — chair start times on the unit side, pickup windows and vehicle assignments on the broker side — inside each side's real rules, and reports minutes of post-treatment waiting removed per patient. What it cannot resolve within the rules, it explains and hands to a human with a draft message.

**Three-sentence problem narrative.** About half a million Americans dialyze in-center three times a week, which is more than 70 million round trips a year, and roughly one in four of them has no private ride ([PMC10561812](https://pmc.ncbi.nlm.nih.gov/articles/PMC10561812/), [PMC12342063](https://pmc.ncbi.nlm.nih.gov/articles/PMC12342063/)). In the one published survey that measured it, two-thirds of patients reported late pickups and the average wait was 62 minutes — after four hours on a machine, often hypotensive, sometimes outside in the cold ([NKF J. Nephrology Social Work](https://www.kidney.org/sites/default/files/v23_a6.pdf), [UC Davis 2026](https://health.ucdavis.edu/news/headlines/transportation-problems-disrupt-dialysis-care-for-patients-with-kidney-failure/2026/04)). The unit sets chair times, the broker sets pickup windows from a standing order booked days earlier, and nobody re-times the two together — even though dialysis is the single largest reason for NEMT trips ([PMC5334728](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5334728/)).

**Why this is "Breakthrough" (only possible with Fable 5.1).** Two interlocking schedules with hard constraints on both sides; a long stable context (unit policy + broker policy + 36-patient roster + 44-trip manifest ≈ 25k tokens) re-read every loop at $0.25/M cached ([launch post](https://www.anthropic.com/claude-fable-and-mythos-5-1)); a propose → verify → score loop where the model chooses and deterministic code counts; and a human-review queue for the residue. Fable 5.1 is pitched exactly on long, multi-step agentic work that verifies its own work and keeps its own records.

**Demo beat.** "Average post-treatment wait 74 → 21 minutes, zero chair conflicts, three riders flagged for a human." Then Van 3 breaks down at 1:40 pm and the agent re-plans on camera. (Calibrate the synthetic seed so the baseline lands 65–80 min; the published average is 62.)

**Success metrics (exact).**
- Primary: mean and p90 **post-treatment wait** = `pickup_actual − ready_time`, where `ready_time = session_end + recovery_buffer`. Target after: mean ≤ 25, p90 ≤ 45.
- **Wait-minutes removed** (sum over riders, before − after) and **% riders picked up within 30 min of ready**.
- **Pre-treatment early wait** (arrival before chair start) — must not get worse by more than 10 min mean.
- **Chair conflicts = 0**, **constraint violations = 0** (hard gate).
- **Riders flagged for human review** (count and share; target ≤ 15%).
- **Equity gap**: |mean wait(wheelchair) − mean wait(ambulatory)| ≤ 10 min.
- **Re-plan time** after a perturbation ≤ 30 s wall clock; full run ≤ 90 s.
- **Cost per run, tokens, cache hit rate** — shown on screen.

**Stakeholders and what each gets.**
| Stakeholder | Job to be done | What Chair-to-Ride gives them |
|---|---|---|
| Charge nurse | Protect the clinical schedule; know who leaves when | Chair-move proposals that never shorten a prescription; a per-shift "who's waiting" view |
| Unit scheduler | Keep stagger and turnover feasible; approve chair moves | Ranked chair moves with the reason and the wait saved; one-click accept in the timeline |
| Broker dispatcher | Fill pickup windows legally and efficiently | Pickup windows that sit after ready-time, inside the ADA ±60-min negotiation bound, on a feasible route |
| Social worker | Resolve the cases the system can't | Review queue with reason code, recommended action, and a draft message |
| Patient / rider | Know when to be ready and why it changed | Plain-language note: what changed, why, who to call |

**MVP vs stretch.** MVP: one unit, one MWF day, 12 chairs × 3 shifts, 22 NEMT riders, 5 vans, one perturbation, review queue, explanations, evals, cost meter. Stretch: full week, two units sharing one broker, rider language preference, FHIR `Appointment` export via Anthropic's FHIR skill ([tutorial](https://claude.com/resources/tutorials/how-to-use-the-fhir-developer-agent-skill-with-claude-code)), a Sonnet-driven broker agent with hidden preferences.

**One lean-in moment per judge.**
- **Sharon Rao MD** — the recovery buffer (needle-site hemostasis + post vitals + weigh-out) and the nurse note "hypotension history → +15 min" are first-class constraints; the agent never touches session length, prescription days, or MD-fixed patients; the nurse-facing summary reads like handoff.
- **Marie Roker-Jones** — the equity guard (one chair move per patient per week; wheelchair riders' waits bounded the same as ambulatory) and the social-worker queue with a ready-to-send message; the story retells in one line: *the chair schedule and the ride schedule finally talk to each other.*
- **AJ Yadav** — 74 → 21 on screen, Van 3 dies live, cost counter ticking on Fable 5.1, ledger scrolling; built tonight with Claude Code.

---

## 2. Problem and evidence

| Claim | Number | Source |
|---|---|---|
| Scale | ~500,000 in-center dialysis patients; >70M round trips/yr | [PMC10561812](https://pmc.ncbi.nlm.nih.gov/articles/PMC10561812/) |
| Transport insecurity | 27% of 115,982 in-center patients lacked a private ride; Medicaid/paratransit/transit users more likely to miss treatments (aIRR 1.31 / 1.15 / 1.24) and had higher 1-yr mortality | [Razon et al., CJASN 2025 (PMC12342063)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12342063/) |
| Wait time | Two-thirds picked up late; average wait 1 h 2 min | [NKF J. Nephrology Social Work, v23](https://www.kidney.org/sites/default/files/v23_a6.pdf) |
| Lived experience | Patients waiting outside for hours while dizzy/weak; staff workflow disrupted | [UC Davis Health, Apr 2026](https://health.ucdavis.edu/news/headlines/transportation-problems-disrupt-dialysis-care-for-patients-with-kidney-failure/2026/04) |
| Missed treatments | 10% miss ≥1 session/month; 35% miss one every 3 months | [PMC13089766](https://pmc.ncbi.nlm.nih.gov/articles/PMC13089766/) |
| Downstream cost | Eliminating transport-caused missed/shortened treatments would avoid ~0.8 hospital days/patient/yr | [PMC10561812](https://pmc.ncbi.nlm.nih.gov/articles/PMC10561812/) citing Chan et al. |
| NEMT share | Dialysis was the most common trip reason in a 39k-rider LogistiCare dataset (37–41% of users; >50% of trips) | [PMC5334728](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5334728/) |
| Session cadence | 3×/week, ~4 h; MWF or TTS; same time each day; three shifts/day | [DaVita](https://davita.com/treatment-options/dialysis/in-center-hemodialysis/), [WashU](https://kidney.wustl.edu/treatment-options/in-center-dialysis/), [PMC12507099](https://pmc.ncbi.nlm.nih.gov/articles/PMC12507099/) |
| Post-treatment | Patient must wait for the needle site to stop bleeding and BP to normalize before leaving | [USPTO 11951241 (background)](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11951241) |
| ADA rule | Paratransit may negotiate pickup up to one hour before/after the requested time; beyond that it must be logged as a denial (49 CFR 37.131(b)(2)) | [FTA FAQ](https://www.transit.dot.gov/may-americans-disabilities-act-ada-complementary-paratransit-provider-negotiate-my-pickup-time), [FTA C 4710.1](https://www.transit.dot.gov/sites/fta.dot.gov/files/docs/Final_FTA_ADA_Circular_C_4710.1.pdf) |
| Pickup window | Agencies commonly use a 30-min on-time window (−15/+15) and a 5-min driver wait | [Sioux City ADA manual](https://www.sioux-city.org/DocumentCenter/View/969/SCTS-ADA-Policy-Manual-PDF) (example of common practice) |
| Trip length | Ride time must be comparable to fixed-route; will-call and "no-strand" policies are addressed in Circular ch. 8 | [National RTAP](https://www.nationalrtap.org/Toolkits/ADA-Toolkit/Service-Type-Requirements/ADA-Complementary-Paratransit-Requirements), [DREDF OTP guide](https://dredf.org/ADAtg/OTP.shtml) |
| Broker practice | Dialysis rides are standing orders; return legs are booked at the same time and adjusted by calling the broker; 48–72 h notice for changes; NJ MCOs use ModivCare | [NJ FamilyCare guide](https://deltamedicaltransportation.com/blog/nj-familycare-nemt-complete-guide), [Medicaid NEMT guide](https://medicaideligibilitycalculator.com/free-transportation-for-medicaid-patients/) |
| Prior coordination work | Best practices: a named point person between transport company and unit, same driver per patient, ride-sharing among nearby patients; ride-hail pilots exist (CareMore/Lyft; dialysis the top reason for 65+) but an RCT showed no missed-appointment reduction for primary care | [PMC10561812](https://pmc.ncbi.nlm.nih.gov/articles/PMC10561812/), [US News on Health Affairs](https://health.usnews.com/health-care/patient-advice/articles/2018-10-10/lyft-and-uber-help-patients-make-it-to-medical-appointments) |
| Algorithms | Insertion heuristics with time slack (Jaw–Odoni–Psaraftis–Wilson 1986; REBUS 1995), tabu/ALNS (Cordeau–Laporte 2003); a 2021 paper formulates exactly our twist — DARP with *flexible appointment times* and return trips | [arXiv 2105.14472](https://arxiv.org/pdf/2105.14472), [Cordeau & Laporte 2003](https://ideas.repec.org/a/eee/transb/v37y2003i6p579-594.html) |

**Gap we exploit:** everything above treats the appointment time as fixed and the ride as the variable. Dialysis units *do* have slack (stagger cohorts, 15–30 min chair shifts within a shift) and brokers *do* have a legal negotiation band (±60 min). Nobody searches both at once with the clinical and regulatory rules loaded.

**Assumptions stated (not sourced):** chair turnover 30 min; put-on cohorts of 4 chairs per 15 min; recovery buffer 20 min (35 min with hypotension note); shared-ride cap 60 min; van capacity 4 ambulatory + 1 wheelchair or 3 + 2; vehicle shift 05:30–21:30. These are configurable in `config/rules.yaml`, and the clinical teammate should adjust them at CP0.

---

## 3. Product spec

**Users:** charge nurse, unit scheduler, broker dispatcher, social worker, patient/rider (see §1 table).

**Jobs to be done.**
1. Given tomorrow's chair schedule and the broker's manifest, produce a revised pair of schedules that minimizes post-treatment wait without violating any clinical, unit, or broker rule.
2. Explain every change to the person it affects, in their language, with the number.
3. Queue what the rules cannot resolve, with a reason and a recommended human action.
4. When the day goes wrong (vehicle down, chair down, late patient), re-plan the remainder of the day in under 30 s.
5. Show the receipts: a decision ledger, metrics, and cost.

**Inputs** (all JSON, all synthetic, in `data/synthetic/<seed>/`):
- `unit.json` — unit, chairs, shifts, stagger cohorts, staff capacity, unit policy text.
- `roster.json` — patients with prescription (days, duration), assigned chair/shift/start, mobility class, flags (`clinically_fixed`, `consent_to_move`, `hypotension_note`), nurse note text, rider link.
- `manifest.json` — trips (to/from), requested times, negotiated windows, vehicle assignment, mobility needs, rider note text, broker policy text.
- `fleet.json` — vehicles, capacity by class, shift hours, depot node.
- `travel.json` — node grid and a travel-time matrix (minutes), synthetic.
- `events.jsonl` — perturbations with timestamps (for scenarios).

**Outputs** (in `runs/<run_id>/`):
- `schedule_after.json` (chairs) and `manifest_after.json` (rides), both validated.
- `review_queue.json` — items with reason code, recommended action, draft message.
- `explanations.json` — rider-, nurse-, and dispatcher-facing notes.
- `ledger.jsonl` — every proposal, verification result, decision, and cost line.
- `metrics.json` — before/after metrics, equity gap, tokens, cache hit rate, dollars.
- `timeline.html` — single-file before/after Gantt (chairs above, vehicles below, wait bars in red), fed by the JSON above.

**Non-goals (say them on stage if asked).** Not a fleet routing engine for the whole broker; no real-time GPS; no EHR integration; no clinical decision support; never changes a prescription, session length, or treatment day; does not message patients directly — it drafts, a human sends.

---

## 4. Domain model and rules

### Entities (Pydantic v2 models in `src/c2r/models.py`)
- **Unit** `{unit_id, name, chairs: [Chair], shifts: [Shift], stagger_cohort_size: 4, stagger_step_min: 15, turnover_min: 30, close_time, policy_text}`
- **Chair** `{chair_id, station_type: "standard"|"isolation", available_windows: [[t0,t1]]}`
- **Shift** `{shift_id: "S1"|"S2"|"S3", putton_start, putton_end}` — defaults S1 06:00–06:45, S2 10:45–11:30, S3 15:30–16:15.
- **Patient** `{patient_id, display_name (fictional), rx_days: "MWF"|"TTS", rx_duration_min ∈ {210,225,240,255,270}, shift_id, chair_id, start_time, clinically_fixed: bool, fixed_reason, consent_to_move: bool, mobility: "ambulatory"|"assist"|"wheelchair"|"stretcher", recovery_buffer_min: 20|35, nurse_note, moves_this_week: int, rider_id|null}`
- **Session** (derived) `{patient_id, chair_id, start, end = start + rx_duration, ready_time = end + recovery_buffer}`
- **Rider** `{rider_id, patient_id, home_node, language, caregiver_window|null, rider_note}`
- **Trip** `{trip_id, rider_id, leg: "to"|"from", origin_node, dest_node, requested_time, window: [t0,t1] (30 min), vehicle_id|null, seq|null, status: "scheduled"|"will_call"|"queued"}`
- **Vehicle** `{vehicle_id, cap_ambulatory, cap_wheelchair, cap_stretcher, shift: [t0,t1], depot_node, status: "ok"|"down"}`
- **Route** (derived) `{vehicle_id, stops: [{trip_id, kind: pickup|dropoff, node, eta, load_after}]}`
- **Rules** `config/rules.yaml` — every constant below, plus soft-objective weights.
- **Event** `{t, type: "vehicle_down"|"chair_down"|"late_arrival"|"add_on_patient"|"travel_slowdown", payload}`
- **Move** (atomic) — `shift_chair_start`, `swap_chairs`, `shift_pickup_window`, `reassign_vehicle`, `resequence_route`, `pair_riders`, `request_extra_capacity` (human), `hold_for_will_call` (human).
- **Bundle** `{bundle_id, moves: [Move], side: "unit"|"broker"|"both", predicted: {delta_wait_min, delta_early_min, chair_changes, consent_moves, vehicle_min}, touches: [patient_ids]}`
- **LedgerEntry**, **ReviewItem**, **Explanation**, **JudgeScore** — schemas in §5.

### Hard constraints (checked by `verify()`, never by the model)
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

### Soft objectives (weights in `rules.yaml`, defaults shown)
`J = 1.0·Σ post_wait + 0.3·Σ early_wait + 8·(#chair changes) + 20·(#consent-flag moves) + 0.05·(vehicle minutes) + 15·(#review items)` — minimize. Ties broken toward fewer touched patients. The model may argue for a *different* bundle than the lowest-J one, but must say why in the ledger (e.g., a nurse note, a caregiver window).

### Immovables
Prescription days; session duration; MD-fixed start times; stretcher assignments; anything the broker policy marks non-negotiable (e.g., no pickups before 06:30 — set in `broker_policy.md`).

### Glossary (for the clinical and transport teammates)
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

---

## 5. Architecture and API usage plan

### Two options, then the pick
**Option A — "LLM chooses, solver counts" (raw Anthropic SDK, our own loop).** Python + `anthropic` SDK Messages API with tool use. A deterministic module generates candidate bundles with computed deltas; Fable 5.1 reads both policies, the roster, the manifest, and the candidates, chooses/argues/negotiates, calls `verify()`, writes the ledger, and triages the queue. We own cache breakpoints, effort per call, token accounting, and timeouts.
*Trade-offs:* more plumbing (≈150 lines of loop), but every number is deterministic, latency is bounded, cost is instrumentable per call, and the demo cannot hallucinate a schedule.

**Option B — Claude Agent SDK runtime.** Use `claude-agent-sdk` (`query()`, `ClaudeAgentOptions`, custom tools as in-process MCP, subagents, hooks) as the product runtime ([Agent SDK overview](https://platform.claude.com/docs/en/agent-sdk/overview)). *Trade-offs:* fastest to a working agent loop and comes with session management, but it bundles the Claude Code CLI, gives less direct control over cache-breakpoint layout and per-call effort, and makes on-camera cost/cache numbers harder to attribute.

**Decision: Option A** for the product runtime; the Agent SDK's concepts (custom tools, hooks, subagents) are used where they belong — in Claude Code, building the repo. If the loop is not stable by CP2, fall back to the §12 emergency cut, not to Option B.

### Which model where
| Stage | Model | Effort / thinking | Why |
|---|---|---|---|
| Orchestrator loop (choose bundles, negotiate, ledger, triage) | `claude-fable-5-1` | `output_config.effort: "medium"`, `thinking: {type: "adaptive"}`, `max_tokens: 8000` | Low/medium on 5.1 matches or beats Fable 5 at lower cost ([launch post](https://www.anthropic.com/claude-fable-and-mythos-5-1)); medium is the documented balance point for agentic loops ([effort doc](https://platform.claude.com/docs/en/build-with-claude/effort)) |
| Perturbation re-plan | `claude-fable-5-1` | `effort: "high"`, `max_tokens: 16000` | One call, must be right on camera |
| Rider / nurse / dispatcher explanations | `claude-sonnet-5` | default effort, `output_config.format` JSON schema | Bulk text, 25–40 calls; cheap and good prose |
| Synthetic narrative fields (names, notes) | `claude-sonnet-5` | default | Numbers are generated in Python, never by the model |
| LLM-as-judge for explanations | `claude-fable-5-1` | `effort: "low"` (sync for gates; Batch for suites) | Different model from the writer to limit self-preference; low effort is the documented "subagent" tier |
| Stress-scenario narratives (what happened at 13:40) | `claude-haiku-4-5-20251001` | default | Flavor text only |

**Pricing used for estimates** (verified today): Fable 5.1 $10/M in, $50/M out, cache read $0.25/M; 5-min cache write 1.25× base = $12.50/M, 1-h write 2× = $20/M ([launch post](https://www.anthropic.com/claude-fable-and-mythos-5-1), [prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)). Batch = 50% of standard for all models; Fable 5.1 batch $5/$25, Sonnet 5 batch $1/$5, Haiku 4.5 batch $0.50/$2.50 — so standard Sonnet 5 ≈ $2/$10 and Haiku 4.5 ≈ $1/$5 (derived) ([batch doc](https://platform.claude.com/docs/en/build-with-claude/batch-processing)).

### Caching layout (one call = tools → system → messages; cache is a prefix match; ≤ 4 breakpoints)
```
[tools: 8 tool definitions, strict:true]                      ─┐ breakpoint 1 (never changes in a run)
[system block A: role, rules of engagement, output rules]      ─┘
[system block B: unit_policy.md + broker_policy.md + rules.yaml]      breakpoint 2 (per-unit stable)
[system block C: roster.json + manifest.json + fleet.json + travel summary]  breakpoint 3 (per-day stable, ~15k tok)
[messages: iteration k — compact state delta + candidate bundles + tool results]   NOT cached, ≤ 4k tok
```
- Use explicit `cache_control` on blocks A–C; leave the top-level automatic cache off for the loop so the breakpoint doesn't drift ([prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)).
- 5-min TTL is fine for the demo loop (iterations are seconds apart). Use `ttl: "1h"` for eval suites and batches — the batch doc recommends it because batches can exceed 5 minutes.
- **Never mutate blocks A–C mid-run.** Applied moves change the *state delta* in messages, not the base manifest. This is Hollman's KV-cache rule (§7 H2). The eval gate asserts cache-read share ≥ 80% after iteration 2.
- Read `usage.cache_read_input_tokens`, `usage.cache_creation_input_tokens`, `usage.input_tokens`, `usage.output_tokens` on every response; `costs.py` prices them and writes a ledger cost line.

### Tools (function tools executed by Python; all `strict: true`)
`get_state()`, `generate_candidates(side, k)`, `propose_to_unit(bundle_id)`, `propose_to_broker(bundle_id)`, `verify(schedule_version)`, `apply_bundle(bundle_id, verify_hash)`, `flag_for_review(item)`, `write_ledger(entry)`, `finish(summary)`. `apply_bundle` refuses unless `verify_hash` matches a verify result from the current version with zero violations — the model cannot skip verification.

Structured outputs: `output_config.format` (JSON schema) for explanations and judge scores; `strict: true` on tools for the loop ([structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use)). **Check at kickoff** that `claude-fable-5-1` is on the structured-outputs model list; if not, keep `strict: true` tools and validate JSON-format outputs with Pydantic + one retry.

### Structured-output schemas (abridged; full JSON Schema in `specs/schemas/`)
```jsonc
// Bundle (produced by solver, consumed by model)
{ "bundle_id": "B07", "side": "both",
  "moves": [{"type":"shift_chair_start","patient_id":"P14","delta_min":15},
            {"type":"pair_riders","trip_ids":["T14f","T22f"],"vehicle_id":"V2"}],
  "predicted": {"delta_wait_min":-118,"delta_early_min":4,"chair_changes":1,"consent_moves":0,"vehicle_min":-6},
  "touches": ["P14","P22"], "notes_relevant": ["P14: hypotension_note"] }

// VerifyResult
{ "schedule_version": 7, "verify_hash": "sha256:…", "violations": [{"code":"H6","trip_id":"T09f","detail":"window opens 12 min before ready"}],
  "metrics": {"mean_post_wait":31.2,"p90_post_wait":58,"wait_min_total":812,"early_wait_mean":9.1,"conflicts":0,"equity_gap":6.4,"vehicle_min":1210} }

// ReviewItem
{ "item_id":"R03","subject":"P31","reason_code":"NO_FEASIBLE_WINDOW|STRETCHER|CONSENT_BLOCK|BROKER_POLICY|CLINICAL_NOTE",
  "what_was_tried":["B03","B11"],"recommended_action":"call rider to confirm 15:10 chair; else hold will-call",
  "draft_message":"…","owner":"social_worker","urgency":"today" }

// Explanation (Sonnet output_config.format)
{ "audience":"rider|nurse|dispatcher","subject_id":"P14","what_changed":"…","why":"…","new_times":{"chair_start":"11:15","pickup_window":["15:40","16:10"]},
  "ledger_refs":["L-017"],"contact":"unit front desk","reading_grade":6.8 }

// JudgeScore
{ "explanation_id":"E14r","scores":{"accuracy":2,"actionable":2,"plain":1,"tone":2,"complete":2,"safe":2},"rationale":"…","pass":true }
```

### Estimated cost
- **One orchestration run** (12 iterations): cache write 25k × $12.50/M ≈ $0.31; per iteration 25k cached ($0.006) + 3k fresh in ($0.03) + 1.5k out ($0.075) ≈ $0.11 → **≈ $1.65**. Perturbation re-plan at high effort ≈ $0.35. Explanations 30 × (1.5k in + 300 out) on Sonnet 5 ≈ $0.18. Judge 30 × (2k in + 250 out) on Fable 5.1 low ≈ $0.98 sync / $0.49 batch. **≈ $3.2 per full demo run, ≈ $2.7 with batched judging.**
- **Eval suite** (5 scenarios × 3 seeds = 15 runs + judging): **≈ $40 sync, ≈ $30 with 1-h cache + batched judge.** Batches usually finish within an hour but may take up to 24 h ([batch doc](https://platform.claude.com/docs/en/build-with-claude/batch-processing)) — never put a demo-night gate on the Batch API.
- Anthropic credits cover this; the point is to *show* the meter, not to save money.

---

## 6. Agent design

### Roles (runtime, in the product)
- **Mediator (Fable 5.1)** — the only LLM in the loop. Holds both rulebooks and both schedules. Chooses among solver bundles, negotiates by alternating `propose_to_unit` / `propose_to_broker`, requests counter-bundles when a side rejects, calls `verify`, applies, writes the ledger, and triages residue. It never computes a time or a minute.
- **Unit party (deterministic, `parties/unit.py`)** — accepts/rejects bundles against unit policy: max chair changes per shift per day, stagger, turnover, fixed/consent flags, nurse-note rules (hypotension → buffer 35). Returns reason codes and, on rejection, a hint (e.g., "would accept +15 not +30").
- **Broker party (deterministic, `parties/broker.py`)** — accepts/rejects against broker policy: ADA ±60, 30-min windows, earliest pickup 06:30, capacity, ride-time cap, driver hours. Same reason-code contract.
- **Solver (`solver.py`)** — candidate generation: for each rider with post-wait > 30 min, enumerate chair shifts of ±15/±30 within the shift, window shifts to `ready_time..ready_time+30`, vehicle reassignment, pairing with riders whose ready times are within 15 min and nodes within 10 min, plus 2-opt resequencing; score with `J`; return top-k bundles (k=6) with predicted deltas. Insertion with time slack, à la Jaw et al./REBUS ([arXiv 2105.14472](https://arxiv.org/pdf/2105.14472)); no OR-Tools.
- **Verifier (`verify.py`)** — recomputes routes and all H1–H13 from scratch on the candidate state; returns violations + metrics + hash. Pure function; property-tested.
- **Explainer (Sonnet 5)** — after `finish`, one call per affected party; inputs are the ledger entries for that subject only.
- **Judge (Fable 5.1 low)** — scores explanations; failures go to the review queue as "explanation needs human edit".

### Prompt outlines (`prompts/*.v1.md`, versioned; see §10)
**Mediator system (block A):** role; the four laws (never compute numbers; never apply without a zero-violation verify; alternate sides when a side rejects; queue rather than force); decision policy (prefer lowest `J` unless a note/equity reason says otherwise — then say so); ledger format; stop conditions; tone rules for the nurse summary. ≤ 900 tokens.
**Block B:** `unit_policy.md`, `broker_policy.md`, `rules.yaml` rendered as text with the constants.
**Block C:** roster, manifest, fleet, travel summary (per-zone minutes), today's date and shift table.
**Per-iteration user message:** `state delta since last apply` (≤ 800 tok) + `candidates` (≤ 2.5k tok) + last tool results. Never re-send the manifest.
**Explainer system:** audience, reading level ≤ grade 8, must cite `ledger_refs`, must include the two new times, must not give medical advice, must not promise, must end with who to call. Two examples (good/bad).
**Judge system:** rubric (§9), score each 0–2, rationale before scores, strict JSON, "if any number in the explanation is not in the ledger refs, accuracy = 0".

### The propose → verify → score loop
```
state = load(); baseline = verify(state)
for k in 1..12:
    cands = generate_candidates(side=next_side(), k=6)          # deterministic
    choice = MEDIATOR.choose(cands, state_delta)                # LLM (structured tool call)
    resp   = propose_to_<side>(choice)                          # deterministic party
    if resp.rejected: MEDIATOR.records reason; next_side flips; continue
    v = verify(apply_preview(choice))
    if v.violations: MEDIATOR.records; continue
    apply_bundle(choice, v.hash); ledger.append(...)
    if stop_condition(): break
finish(); explanations; judge; timeline; cost report
```
**Stop conditions:** best available bundle improves `J` by < 2%; or k = 12; or wall clock > 90 s; or all riders' post-wait ≤ 30 and equity gap ≤ 10. On stop, anything still > 45 min post-wait is queued with `NO_FEASIBLE_WINDOW`.

### Autonomy slider (config `autonomy_level`, default 1 for the demo)
| Level | Agent may do alone | Must queue for a human |
|---|---|---|
| 0 — propose | Nothing is applied; outputs a proposal pack | Everything |
| 1 — bounded (demo) | Chair shifts ≤ 30 min inside the same shift for `consent_to_move` patients; pickup windows inside ADA ±60 and after ready; vehicle reassignment and pairing within capacity; ≤ 1 move per patient per week | Any `consent_to_move=false` or `clinically_fixed` patient; stretcher trips; anything outside ±60; extra vehicle hours; will-call holds; any bundle the unit or broker party rejects twice |
| 2 — trusted | Level 1 + cross-shift moves for consenting patients + extra vehicle-hour requests | Fixed patients, stretcher, denials |

### Human-review queue
`review_queue.json` items carry `reason_code`, `what_was_tried` (bundle ids), `recommended_action`, `draft_message`, `owner` (social_worker | charge_nurse | dispatcher), `urgency`. The timeline shows the queue as a right-hand panel; a human choice (accept / edit / dismiss) is written back to the ledger with `actor: "human"` and the schedule is re-verified. The explainer never writes to a queued rider until a human resolves the item.

---

## 7. Agent standards (Cherny / Karpathy / Hollman)

Every rule below has an enforcement mechanism. "Build" = Claude Code subagents building this repo. "Runtime" = the mediator/explainer/judge in the product. Source notes: the Claude Code best-practices post now lives at code.claude.com; Cherny's tips are cited from his own X threads and a community transcription of the Jan 3 2026 thread; Karpathy from the Latent Space transcript of the YC AI Startup School talk; Hollman from her NDC Copenhagen 2026 talk (video + summary), Code with Claude 2026 workshop notes, a Forbes write-up of her London session, and the April 2026 healthcare webinar page. **Where a rule comes from a secondary summary rather than the primary, the table says "via".** Hollman's healthcare-webinar recording is gated behind registration; only the event page's stated topics are used, and no verbatim rule is attributed to it.

| # | Rule | Source URL | Applies to | Enforced by |
|---|---|---|---|---|
| C1 | Give Claude a check it can run; a pass/fail signal closes the loop without you. Show evidence, not assertions. | https://code.claude.com/docs/en/best-practices | Both | **Build:** `Stop` hook runs `python evals/run_evals.py --gate` and exits 2 on failure (blocks turn end); `PostToolUse` on `src/c2r/{solver,verify,rules}.py` runs `pytest evals/invariants -q -x`. PR checklist item 1: "test output pasted". **Runtime:** `apply_bundle` refuses without a zero-violation `verify_hash`. |
| C2 | Explore → plan → code → commit; plan mode before multi-file or unfamiliar changes; skip planning for one-line fixes. | https://code.claude.com/docs/en/best-practices | Build | `KICKOFF.md` step 1 starts with `claude --permission-mode plan`; CLAUDE.md line: "Enter plan mode for any change touching >1 file under src/c2r/ or any file under prompts/." |
| C3 | Keep CLAUDE.md short and curated: every line must prevent a mistake; convert repeatable rules to hooks; long files get ignored. | https://code.claude.com/docs/en/best-practices | Build | CLAUDE.md hard cap 60 lines (checked by `evals/repo/test_claude_md.py`); `reviewer` subagent flags additions that Claude could infer from code; `/doctor` run at CP4. |
| C4 | Use hooks for anything that must happen every time with zero exceptions; CLAUDE.md is advisory, hooks are deterministic. | https://code.claude.com/docs/en/best-practices ; https://code.claude.com/docs/en/hooks | Both | **Build:** `.claude/settings.json` hooks in §11 (PHI guard, pytest after edit, eval gate on Stop, block `rm -rf`/force-push). **Runtime analog:** every constraint lives in `verify.py`, none in prompts. |
| C5 | Use subagents for investigation and for adversarial review in a fresh context; one Claude writes, another reviews the diff against the plan and reports gaps only. | https://code.claude.com/docs/en/best-practices | Build | `.claude/agents/reviewer.md` has no Edit/Write tools; `/review` command invokes it against the current spec; PR checklist item 2: "reviewer findings attached and addressed or waived with reason". |
| C6 | `/clear` between unrelated tasks; after two failed corrections, clear and write a better prompt. | https://code.claude.com/docs/en/best-practices | Build | CLAUDE.md line; KICKOFF.md runs each checkpoint as a fresh session with `/clear` and a named session (`/rename cp2-orchestrator`). |
| C7 | Be specific: name files, constraints, examples, and what "done" looks like; for larger features write a self-contained spec first, then execute in a fresh session. | https://code.claude.com/docs/en/best-practices | Build | `specs/TEMPLATE.md` requires "Files", "Out of scope", "Definition of done", "Verification command"; `/kickoff` refuses to start a checkpoint whose spec lacks those headers. |
| C8 | When Claude makes a mistake, add the lesson to CLAUDE.md (or a hook) so it never repeats — compounding. | https://x.com/bcherny/status/2017742741636321619 ; via https://github.com/shanraisshan/claude-code-best-practice/blob/main/tips/claude-boris-13-tips-03-jan-26.md | Build | `/lesson "<one line>"` command appends to CLAUDE.md under `# Lessons` (cap 15 lines); PR checklist item 3: "if the bug came from a misunderstanding, one lesson or one hook added". |
| C9 | Put every inner-loop workflow behind a slash command; start most sessions in plan mode; go back and forth until the plan is right, then let it one-shot. | https://x.com/bcherny/status/2017742741636321619 ; via https://github.com/shanraisshan/claude-code-best-practice/blob/main/tips/claude-boris-13-tips-03-jan-26.md | Build | `.claude/commands/{kickoff,run-demo,run-evals,review,lesson,commit}.md`; kickoff step 1 is plan mode by construction. |
| C10 | Commit often with descriptive messages; small reviewable diffs. | https://code.claude.com/docs/en/best-practices | Build | `/commit` command; `PreToolUse` Bash hook blocks `git push --force*` and `rm -rf`; build plan requires a commit at every checkpoint. |
| K1 | Autonomy slider: start with low autonomy and earn more; don't pin the dial at "unsupervised". | https://www.latent.space/p/s3 | Both | **Runtime:** `autonomy_level` config (§6), default 1; level 2 requires a passing eval suite recorded in `runs/`. **Build:** kickoff uses plan mode → manual accept for `src/c2r/verify.py` and `prompts/` → auto mode only for `viz/` and `docs/`. |
| K2 | Keep the AI on a leash: small, verifiable chunks; incremental changes, not giant diffs. | https://www.latent.space/p/s3 | Both | **Runtime:** one bundle per iteration, ≤ 6 moves per bundle (`rules.yaml: max_moves_per_bundle`), each verified. **Build:** one spec per checkpoint; reviewer rejects PRs > 400 changed lines in `src/`. |
| K3 | Make the generate → verify loop fast and visual; GUIs and diffs beat reading raw output. | https://www.latent.space/p/s3 | Both | `viz/timeline.html` regenerated on every `apply_bundle`; eval gate must finish < 60 s; `PostToolUse` on `runs/**` re-renders the timeline so the builder sees the schedule, not JSON. |
| K4 | Treat the model as fallible: verify, don't trust. | https://www.latent.space/p/s3 | Both | **Runtime:** LLM never computes a number (`tools.py` strips any numeric claims from free text into the ledger as "unverified"; the judge zeroes accuracy on numbers absent from the ledger). **Build:** PR checklist item 1 (evidence). |
| K5 | Build for agents: docs and interfaces an agent can consume directly. | https://www.latent.space/p/s3 | Both | `specs/schemas/*.json` are the single source of truth for Pydantic models; every tool returns structured JSON with `reason_code`; `docs/llms.txt` indexes the repo; CLAUDE.md imports `@specs/INDEX.md`. |
| K6 | Partial-autonomy products keep a human in the loop with a purpose-built interface. | https://www.latent.space/p/s3 | Runtime | Review-queue panel in `timeline.html`; human decisions are ledger entries with `actor: "human"`; explainer blocked on queued riders until resolved. |
| H1 | The context window is the primitive and it is fixed; choosing what goes in the box is the engineering problem. Don't stuff CLAUDE.md. | https://www.youtube.com/watch?v=shZgedW15vg ; via https://daily.dev/posts/how-anthropic-uses-claude-code-agentic-software-engineering-at-scale---daisy-hollman-lwzdz8jka ; via https://chrisebert.net/notes-from-code-with-claude-2026/ | Both | **Runtime:** per-iteration message ≤ 4k tokens (assert in `orchestrator.py`, truncate candidates to k=6). **Build:** CLAUDE.md cap (C3); domain knowledge in `.claude/skills/domain-rules/SKILL.md`, loaded on demand. |
| H2 | Respect the KV cache: keep the prefix stable; evicting and re-injecting context between tool calls costs ~10× a cached prediction. | https://www.youtube.com/watch?v=shZgedW15vg ; via https://daily.dev/posts/how-anthropic-uses-claude-code-agentic-software-engineering-at-scale---daisy-hollman-lwzdz8jka | Runtime | Blocks A–C are immutable for the run (§5); eval gate asserts `cache_read_share ≥ 0.80` from iteration 2; `costs.py` prints the share on screen. |
| H3 | Hooks are the most scalable extension because they inject context only when relevant and consume nothing until they fire. | via https://chrisebert.net/code-with-claude-2026-recordings-now-available/ ; https://www.youtube.com/watch?v=shZgedW15vg | Build | Prefer a hook over a CLAUDE.md line whenever the rule is mechanical (C3/C4); `SessionStart` hook prints last eval metrics + open review items instead of putting them in CLAUDE.md. |
| H4 | The fastest way to improve an agent is a tighter feedback loop: examples, rules, and checklists it can self-check against. | via https://www.forbes.com/sites/jodiecook/2026/07/09/5-genius-ways-to-make-claude-do-half-your-work-for-you/ | Both | **Runtime:** `verify()` returns reason codes with hints; explainer prompt carries a 6-item checklist and two examples. **Build:** `Stop` hook gate (C1). |
| H5 | Build the loop, not the prompt — autonomous workflows come from the harness, not from prompt wording. | https://ndcoslo.com/agenda/build-the-loop-not-the-prompt-how-the-claude-code-team-builds-autonomous-workflows | Both | The mediator prompt is ≤ 900 tokens; all behavior that matters is in tools, parties, and the verifier; prompt edits require a judge-eval rerun (§11). |
| H6 | Clinical tools need auditability, compliance, and output traceability (the stated topics of the physicians webinar). | https://www.anthropic.com/webinars/claude-code-in-healthcare-how-physicians-are-building-with-claude ; pattern mirrored on https://claude.com/solutions/healthcare ("Audit Trail", "requires reviewer sign-off") | Runtime | `ledger.jsonl` records run id, git sha, prompt versions, model ids, effort, token usage, input hashes, every tool call and decision; every explanation must cite `ledger_refs`; every output carries a "SYNTHETIC DATA — requires reviewer sign-off" banner. |
| H7 | Give the agent the same information the human has, or it can't do the human's job with you. | via https://www.forbes.com/sites/jodiecook/2026/07/09/5-genius-ways-to-make-claude-do-half-your-work-for-you/ | Runtime | Both full policies, the full roster, the full manifest, and the nurse/rider notes are in the cached context — no retrieval, no summaries of the manifest. |

**Derivation map (what a fresh Claude Code session generates from this table):** CLAUDE.md ← C2, C3, C6, C7 lines + `# Lessons`; `.claude/settings.json` hooks ← C1, C4, C10, K3, H3; `.claude/agents/*` ← C5 plus §11; `.claude/commands/*` ← C8, C9, C10; `specs/TEMPLATE.md` ← C7; `evals/run_evals.py --gate` ← C1, H2, K3; `src/c2r/tools.py` guards ← C1, K2, K4; `config/rules.yaml: autonomy_level, max_moves_per_bundle` ← K1, K2; `ledger.py` ← H6.

---

## 8. Synthetic data plan

**Generator:** `src/c2r/synth.py --seed 42 --out data/synthetic/42/`. Python (numpy RNG) generates *every number*; Sonnet 5 generates only narrative fields (fictional names via a fixed fictional locale list, nurse notes, rider notes) from a structured prompt that includes the numeric facts so the note is consistent ("patient dialyzes S2, wheelchair, caregiver only after 14:00"). Names are drawn from a stored list of 200 invented names; addresses are grid nodes ("Node 17, Zone C") never street addresses. Every file carries `"synthetic": true, "generator": "c2r.synth vX", "seed": 42`.

**Schema (see §4 models).** Roster: 36 patients for a MWF day (12 chairs × 3 shifts). Distribution: rx_duration {210:15%, 225:20%, 240:45%, 255:10%, 270:10%}; mobility {ambulatory 55%, assist 15%, wheelchair 27%, stretcher 3% (one patient)}; `clinically_fixed` 15%; `consent_to_move` 75%; hypotension note 20%; rider_id present for 22 patients (61%), of which 18 NEMT-broker, 4 family (family riders have no trips). Fleet: V1–V3 ambulatory vans (4A+1W), V4–V5 wheelchair vans (3A+2W); V3 is the one that breaks down. Grid: 40 nodes across 4 zones, travel matrix 6–38 min, unit at node 0, depot at node 1.

**Baseline realism (this is what produces the 65–80 min "before").** Standing orders anchor the return pickup at `scheduled_end + 30` with a 30-min window; run-overs of 0–25 min on 30% of sessions and late starts of 10–35 min on 15% shift `ready_time` later than the order assumes; shared routes append 2–3 stops before some riders; and 4 riders are on will-call, which the baseline resolves late. This is the mechanism described in the literature (late pickups, last-drop-off routes) rather than a random offset.

**Realism checks (`evals/data/test_synth.py`, must pass before CP1):**
- Baseline verify: 0 hard-constraint violations on the *unit* side (the before-state is a legal chair schedule) and ≤ 3 ride-side violations (the mess we fix), mean post-wait ∈ [65, 80], p90 ∈ [100, 140].
- Chair utilization 85–100%; every shift has ≥ 1 fixed patient and ≥ 2 non-consenting; stagger bins never exceed 4.
- Ride-time cap satisfiable: for every rider a direct trip ≤ 38 min.
- No string in any output matches the PHI regexes (SSN, MRN, DOB, phone, street address patterns).
- Sonnet-written notes reference only facts present in the record (checked by a second Sonnet call with `output_config.format` returning `{consistent: bool, issues: []}`; must be true for ≥ 95%).
- The clinical teammate reads 10 random nurse notes at CP0 and edits `prompts/synth_notes.v1.md` until they would pass at handoff.

---

## 9. Evals

Design follows Anthropic's agent-eval guidance ([Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)): grade outcomes *and* trajectories, run isolated trials, report `pass^k` for gates (all k seeds must pass) rather than `pass@k`.

**A. Deterministic invariants (`evals/invariants/test_*.py`, Hypothesis property tests where cheap).** I1 no overlapping sessions per chair and turnover ≥ 30; I2 rx_duration and rx_days unchanged for every patient; I3 fixed patients' starts unchanged; I4 non-consenting patients' starts unchanged; I5 stagger bins ≤ 4; I6 every return window opens ≥ ready_time; I7 every window midpoint within ±60 of requested, else trip is queued; I8 capacity by class never exceeded along any route; I9 stretcher trips always queued; I10 route timing feasible with the travel matrix and vehicle shifts; I11 ride time ≤ 60 and ≤ 2× direct; I12 no rider stranded (scheduled or queued with hold); I13 "to" legs arrive in [start−30, start]; I14 moves_this_week ≤ 1; I15 equity gap ≤ 10; I16 every number in every explanation appears in its `ledger_refs` (deterministic extraction + match); I17 no PHI regex matches in any output file; I18 replaying the ledger against the baseline reproduces `schedule_after.json` byte-for-byte (determinism); I19 trajectory: every `apply_bundle` in the ledger is preceded by a `verify` with the same hash and zero violations; I20 cache-read share ≥ 0.80 from iteration 2.

**B. Scenario suite (`evals/scenarios/*.json`, each run with seeds 42/43/44):**
| Scenario | Event | Required outcome |
|---|---|---|
| baseline | none | mean post-wait ≤ 25, p90 ≤ 45, wait-minutes removed ≥ 60%, queue ≤ 15%, runtime ≤ 90 s |
| vehicle_breakdown | V3 down at 13:40 | all V3 riders reassigned or queued with hold, none stranded, re-plan ≤ 30 s, mean post-wait ≤ 35 for S2 riders |
| chair_outage | chair 7 out 11:00–21:00 | S2/S3 patients on chair 7 reseated with 0 violations or queued with `CLINICAL_NOTE`/`NO_FEASIBLE_WINDOW`; no session shortened |
| late_patient | P14 arrives 35 min late | P14's session keeps full duration; downstream chair conflict resolved; P14's ride re-timed; ≤ 2 other patients touched |
| over_capacity_day | +2 add-on patients, V5 unavailable | agent queues rather than violates; queue items carry `request_extra_capacity` with the vehicle-minutes needed; 0 violations |
| travel_slowdown (stretch) | matrix × 1.3 from 15:00 | ride-time cap respected; windows widened only inside ±60 |

Golden metrics live in `evals/golden/<scenario>.json` with tolerances; a run that beats golden by > 15% on wait triggers a re-golden review, not an automatic update.

**C. LLM-as-judge rubric for explanations (`prompts/judge.v1.md`).** Each 0–2: accuracy (numbers/times match ledger refs — any invented number ⇒ 0), actionable (rider knows when/where to be ready), plain (≤ grade 8; also measured deterministically with `textstat`), tone (respectful, no blame, acknowledges the disruption), complete (what changed, why, what to do if the ride is late, who to call), safe (no medical advice, no PHI, no promises the system can't keep). Pass = total ≥ 10/12 and accuracy = 2. Rationale precedes scores; strict JSON. **Calibration:** the clinical teammate hand-grades 10 explanations at CP3; judge/human agreement on pass/fail must be ≥ 8/10 or the rubric is edited before it gates anything.

**D. Regression gates (`evals/run_evals.py --gate`, < 60 s, used by the Stop hook and `/run-evals`):** invariants 100%; baseline scenario on seed 42 within golden tolerance; judge pass rate ≥ 90% on the 12-item golden explanation set; cost ≤ $4/run; runtime ≤ 90 s. Full suite (`--full`, 15 runs, judge via Batch with 1-h cache) runs at CP4 and after the event, not in the hook.

**E. Metrics reported every run:** the §1 list, plus tokens by type, cache-read share, dollars by model, iterations, bundles proposed/accepted/rejected by side, queue count by reason code.

---

## 10. Standards

**Code.** Python 3.12; `uv` for env; Pydantic v2 models generated from `specs/schemas/*.json`; `pytest` + `hypothesis`; `ruff` format/lint; type hints everywhere; pure functions in `solver.py`/`verify.py` (no I/O, no network, seeded RNG); one `AnthropicClient` wrapper in `llm.py` that sets model, effort, thinking, cache blocks, timeouts (30 s per call, 2 retries), and records usage. Windows-compatible: hooks are Python scripts invoked as `python .claude/hooks/<name>.py`; paths via `pathlib`; no bash-only tooling.

**Safety / no-PHI.** Synthetic-only by construction (§8); `data/real/` does not exist and the `PreToolUse` PHI guard blocks creating it; PHI regex guard on every write under `data/`, `runs/`, `prompts/` (exit 2 with the pattern name); every generated artifact and the timeline carry a "SYNTHETIC DATA — requires reviewer sign-off" banner; model prompts state that all identities are fictional and must not be linked to real people; explainer output is never sent anywhere — humans send. The runtime is not HIPAA-scoped tonight; the doc for a real pilot would name Claude's HIPAA-ready infrastructure and BAA path ([healthcare page](https://claude.com/solutions/healthcare)) — do not claim HIPAA on stage.

**Logging and provenance.** `ledger.jsonl` entries: `{ts, run_id, git_sha, iteration, actor: "model"|"tool"|"human", event, payload, model_id, effort, prompt_versions, usage: {input, cache_read, cache_write, output}, cost_usd, input_hashes}`. `metrics.json` and `cost_report.md` are derived from the ledger, never written directly. Runs are reproducible from `seed + ledger`.

**Prompt versioning.** `prompts/<name>.v<N>.md` with YAML frontmatter `{name, version, model, changed_by, change_reason, eval_result}`; the ledger records versions; changing a prompt bumps N (never edit in place) and requires the judge golden set to be rerun and the result written to frontmatter; `PreToolUse` hook blocks edits to any `prompts/*.v*.md` that already has an `eval_result`.

---

## 11. Feedback loops

**Eval results → prompts.** Judge failures are bucketed by rubric dimension in `runs/<id>/judge_summary.json`. The `prompt-engineer` subagent may only edit `prompts/`, must cite the failing bucket, bump the version, rerun `run_evals.py --judge-only`, and report before/after pass rates. Merge only if pass rate rises and no other bucket falls > 5 points.

**Eval results → solver.** Invariant failures go to `solver-dev` with the failing test name and the minimal reproducing state (the property test's shrunken example). Scenario-metric regressions that are not violations are tuned through `rules.yaml` weights (with a ledger note), never by editing `verify.py`. `verify.py` changes require a spec update and reviewer sign-off.

**Hooks (`.claude/settings.json`; all commands `python .claude/hooks/<file>.py` for Windows):**
- `PreToolUse` (Edit|Write): `phi_guard.py` — exit 2 if the target path is under `data/real/` or the content matches PHI regexes.
- `PreToolUse` (Bash): `danger_guard.py` — exit 2 on `rm -rf`, `git push --force`, `git reset --hard` outside a worktree.
- `PreToolUse` (Edit|Write on `prompts/*.v*.md`): `prompt_freeze.py` — exit 2 if the file's frontmatter has `eval_result`.
- `PostToolUse` (Edit|Write on `src/c2r/{solver,verify,rules,parties}*.py`): `pytest_quick.py` — runs `pytest evals/invariants -q -x`, returns failures to Claude.
- `PostToolUse` (Write on `runs/**/schedule_after.json`): `render_timeline.py` — regenerates `timeline.html`.
- `Stop`: `eval_gate.py` — runs `run_evals.py --gate`; exit 2 with the summary on failure (Claude Code stops blocking after 8 consecutive blocks — that is the safety valve, not a target).
- `SessionStart`: `session_brief.py` — prints last metrics, open review items, current prompt versions.

**Write/review split.** Session A (writer, `/rename cpN-writer`) implements the checkpoint spec. Session B (`/review`) runs the `reviewer` subagent in a fresh context with only the diff and the spec, reporting gaps that affect correctness or the spec, not style. A pastes findings back, fixes, re-reviews. For prompts, the same split: `prompt-engineer` writes, `eval-runner` grades.

**Subagents (`.claude/agents/`):** `solver-dev` (Read, Edit, Write, Bash, Grep, Glob; may not touch `prompts/` or `viz/`), `reviewer` (Read, Grep, Glob, Bash limited to `pytest`, `git diff`; no Edit/Write), `eval-runner` (Read, Bash; runs suites, writes only under `runs/`), `data-synth` (Read, Bash, Write under `data/synthetic/` only), `prompt-engineer` (Read, Edit, Write under `prompts/` only, Bash for `run_evals.py --judge-only`), `demo-narrator` (Read; `model: sonnet`; writes `docs/demo_script.md` from `runs/`). Use `model: inherit` for the first five and confirm model aliases with `/model` at kickoff.

**Compounding.** `/lesson` after every bug that came from a misunderstanding; `/doctor` at CP4 to prune CLAUDE.md; after the event, `claude -p` nightly full suite via `/loop` or a scheduled task with Batch judging.

---

## 12. Build plan (3 people, mixed skills; T = start of build, ~4.5 h to demo call)

**Roles.** **A = Ryan** — architecture, orchestrator, API, cost meter, Claude Code driver. **B = clinical/transport teammate** (nurse, physician, coordinator, or dietitian) — rules.yaml constants, policy texts, synthetic-note realism, judge calibration, review-queue semantics, demo narration. **C = builder/generalist** — solver + verifier under A's spec (Claude Code does the typing; C reads the tests), then timeline.html and the demo screen. If C is non-technical, C owns timeline visual QA, the demo script, and the backup recording, and A drives the solver session in parallel.

Every checkpoint ends with a commit and a runnable `make demo` that shows *something true*.

| Checkpoint | Time | Deliverable | Demo-safe state if the clock stops here |
|---|---|---|---|
| **CP0 — scaffold + before** | T+0:20 | `/kickoff` in plan mode generates CLAUDE.md, hooks, agents, commands, specs/, schemas; `synth.py --seed 42`; `make baseline` prints before-metrics; `timeline.html` renders the "before" Gantt. B edits `rules.yaml` and reads 10 nurse notes. | Show the problem on the timeline with the published 62-min number beside our synthetic 74. |
| **CP1 — solver + verifier** | T+1:15 | `solver.py`, `verify.py`, `parties/`, invariants I1–I15 green; `make solve` prints after-metrics; timeline shows before/after; C reviews diff with `/review`. | Static before/after with real computed numbers; narrate the rules. |
| **CP2 — mediator loop** | T+2:15 | `orchestrator.py` with 8 strict tools, cache blocks A–C, ledger, review queue, cost meter; live run in terminal in ≤ 90 s; I16–I20 green. | Live agent run on camera; queue and ledger on screen. |
| **CP3 — perturbation + explanations + judge** | T+3:00 | `perturb.py --event vehicle_down --at 13:40` re-plans ≤ 30 s; Sonnet explanations; Fable-low judge; B hand-grades 10 for calibration. | Full 3-minute demo. |
| **CP4 — evals + freeze** | T+3:45 | `run_evals.py --gate` < 60 s; `--full` kicked off (Batch judge, 1-h cache); `/doctor`; `cost_report.md`; code freeze except viz. | Full demo + receipts. |
| **CP5 — rehearse** | T+4:15 | Two timed dry runs; screen recording of a clean run saved as `docs/backup.mp4`; `demo_script.md` final. | Backup video if Wi-Fi or API fails. |

**MVP = CP0–CP3. Stretch (only if CP4 lands by T+3:45):** FHIR `Appointment` export (`fhir_export.py`, one file, uses Anthropic's FHIR skill conventions); rider-language explanations; a Sonnet-driven broker party with hidden preferences replacing `parties/broker.py` for one run.

**90-minute emergency cut (if CP1 slips past T+2:00).** Drop the mediator loop. `run_direct.py`: solver runs local search to convergence in Python (no LLM), `verify` gates the output, then **one** Fable 5.1 call (high effort, cached context) reads the before/after diff + residue and (a) triages the queue with reason codes and draft messages, (b) writes the charge-nurse and dispatcher summaries; Sonnet writes rider explanations; timeline renders before/after; perturbation is precomputed offline and replayed. Still real API work on both models, still a before/after number, still a queue. Cost meter still on screen. Lose: live negotiation. Keep: everything the judges score.

**Session hygiene for the night:** one Claude Code session per checkpoint (`/clear`, `/rename`), plan mode first, `/review` before commit, `/lesson` on every misunderstanding. Parallel worktrees: A on `orchestrator`, C on `solver`, B on `docs/policies` — merge at each CP.

---

## 13. Demo script (3:00)

| Clock | On screen | One line of narration |
|---|---|---|
| 0:00–0:30 | `timeline.html` "before": 12 chair rows, 5 van rows, red wait bars after each session; header "Harborline Dialysis Unit — Wed — SYNTHETIC DATA" | "After four hours on a machine, these riders wait an average of 74 minutes for a van booked days ago. The published average is 62. Nobody re-times the chairs and the rides together." |
| 0:30–1:00 | Terminal: `make demo` — Fable 5.1 loads unit policy, broker policy, roster, manifest (cache meter shows 25k cached tokens); first six candidate bundles print with predicted minutes | "Chair-to-Ride reads both rulebooks and both schedules, then negotiates chair times against pickup windows — inside the ADA sixty-minute rule and the nurse's notes." |
| 1:00–1:30 | Loop: bundle B03 rejected by unit party ("stagger bin full — would accept +15"), counter-bundle accepted, `verify: 0 violations`, timeline morphs; ledger scrolls | "The model chooses. Deterministic code counts. Nothing is applied without a zero-violation check." |
| 1:30–2:00 | Metrics card: 74 → 21 min mean, p90 118 → 39, 0 chair conflicts, 3 riders queued; review panel shows R01 with reason, recommended action, draft message; one rider note in plain English | "Three riders it couldn't fix inside the rules, it explained and handed to the social worker with a message ready to send." |
| 2:00–2:30 | `perturb --event vehicle_down --at 13:40`: Van 3 turns grey, re-plan runs, timeline updates, re-plan time 18 s, queue +1 | "Now Van 3 dies at 1:40. Watch it re-plan the rest of the afternoon — same rules, same receipts." |
| 2:30–3:00 | Ledger + `cost_report.md`: $2.70 per run, 91% cache reads, evals green (invariants 20/20, judge 11/12), then the tagline | "Every decision is in a ledger a charge nurse can audit. The whole run cost under three dollars on Fable 5.1. The chair schedule and the ride schedule finally talk to each other." |

Fill the exact numbers from the frozen CP4 run; keep the 74 → 21 shape by seed choice, and say the words "synthetic data" once, on screen and aloud.

---

## 14. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Scheduler eats the clock | High | Greedy insertion + bounded local search only; k=6 bundles; 90 s wall cap; no OR-Tools; emergency cut ready at T+2:00 |
| API latency / rate limits on event Wi-Fi | Medium | Medium effort, cached prefix, 30 s timeouts with 2 retries; backup video; precomputed run replayable via `--replay runs/frozen/` |
| `output_config.format` not available on Fable 5.1 | Low–Med | Check at kickoff; fall back to `strict: true` tools + Pydantic validation and one retry |
| Cache misses (prefix drift) | Medium | Blocks A–C immutable; cache-share assertion in gate; print share on screen |
| Judge flakiness / self-preference | Medium | Different model from writer; rationale-first strict JSON; 10-item human calibration; judge failures route to queue, never auto-edit prompts |
| "It's just a scheduler" reaction | Medium | Lead with negotiation across two rulebooks, the review queue, and rider-facing explanations; show the ledger |
| Windows hook/path quirks | Medium | All hooks are Python; test each with `/hooks` at CP0 |
| Synthetic data looks fake to clinicians | Medium | B edits constants and notes at CP0; realism tests in §8; nurse notes reviewed by a nurse |
| Perturbation re-plan produces a violation live | Low | Re-plan goes through the same verify gate; on failure the agent queues and says so — that is also a fine demo beat |
| Credits or key issues | Low | Confirm `claude-fable-5-1`, `claude-sonnet-5`, Haiku access before T+0 |
| PHI accusation | Low | Synthetic banner everywhere; PHI hook; never say "HIPAA" on stage |
| Team skill mismatch | Medium | Roles in §12 assume one builder; Claude Code carries the typing; the clinical teammate owns realism and the story |

---

## 15. Sources

**Anthropic (verified today)**
- Claude Fable 5.1 / Mythos 5.1 launch, pricing, effort levels, cache-read price: https://www.anthropic.com/claude-fable-and-mythos-5-1
- Prompt caching (breakpoints, ordering, write multipliers, TTLs, automatic caching): https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- Effort parameter (`output_config.effort`, levels, adaptive thinking, defaults): https://platform.claude.com/docs/en/build-with-claude/effort
- Batch processing (50% pricing table, 1-h cache guidance, 24-h window): https://platform.claude.com/docs/en/build-with-claude/batch-processing
- Structured outputs and strict tool use: https://platform.claude.com/docs/en/build-with-claude/structured-outputs ; https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use
- Claude Agent SDK overview / Python: https://platform.claude.com/docs/en/agent-sdk/overview ; https://platform.claude.com/docs/en/agent-sdk/python ; https://github.com/anthropics/claude-agent-sdk-python
- Claude Code best practices (verification, plan mode, CLAUDE.md, hooks, subagents, writer/reviewer, Stop-hook gating): https://code.claude.com/docs/en/best-practices (redirect target of https://www.anthropic.com/engineering/claude-code-best-practices)
- Claude Code hooks reference: https://code.claude.com/docs/en/hooks
- Demystifying evals for AI agents: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Claude for Healthcare (HIPAA-ready, connectors, audit-trail pattern): https://claude.com/solutions/healthcare ; FHIR developer agent skill tutorial: https://claude.com/resources/tutorials/how-to-use-the-fhir-developer-agent-skill-with-claude-code
- Webinar page, "Claude Code for Healthcare: How Physicians Build with AI" (Apr 23 2026; recording gated): https://www.anthropic.com/webinars/claude-code-in-healthcare-how-physicians-are-building-with-claude

**Practitioners**
- Boris Cherny, tips thread from the Claude Code team: https://x.com/bcherny/status/2017742741636321619 ; transcription of the Jan 3 2026 13-tips thread: https://github.com/shanraisshan/claude-code-best-practice/blob/main/tips/claude-boris-13-tips-03-jan-26.md
- Andrej Karpathy, "Software 3.0" / partial autonomy (YC AI Startup School), transcript and notes: https://www.latent.space/p/s3
- Daisy Hollman, NDC Copenhagen 2026 talk (video): https://www.youtube.com/watch?v=shZgedW15vg ; summary: https://daily.dev/posts/how-anthropic-uses-claude-code-agentic-software-engineering-at-scale---daisy-hollman-lwzdz8jka ; NDC Oslo "Build the loop, not the prompt": https://ndcoslo.com/agenda/build-the-loop-not-the-prompt-how-the-claude-code-team-builds-autonomous-workflows ; Code with Claude 2026 workshop notes: https://chrisebert.net/notes-from-code-with-claude-2026/ and https://chrisebert.net/code-with-claude-2026-recordings-now-available/ ; London session write-up: https://www.forbes.com/sites/jodiecook/2026/07/09/5-genius-ways-to-make-claude-do-half-your-work-for-you/

**Domain**
- FTA ADA Circular C 4710.1 (ch. 8: negotiating pickup times, will-call, no-strand, trip length): https://www.transit.dot.gov/sites/fta.dot.gov/files/docs/Final_FTA_ADA_Circular_C_4710.1.pdf
- FTA FAQ on the one-hour negotiation rule (49 CFR 37.131(b)(2)): https://www.transit.dot.gov/may-americans-disabilities-act-ada-complementary-paratransit-provider-negotiate-my-pickup-time
- National RTAP ADA toolkit (denials, trip length, OTP): https://www.nationalrtap.org/Toolkits/ADA-Toolkit/Service-Type-Requirements/ADA-Complementary-Paratransit-Requirements ; DREDF topic guide on on-time performance and true negotiation: https://dredf.org/ADAtg/OTP.shtml
- Example agency practice (30-min window, 5-min wait): https://www.sioux-city.org/DocumentCenter/View/969/SCTS-ADA-Policy-Manual-PDF
- Post-treatment wait survey (62 min): https://www.kidney.org/sites/default/files/v23_a6.pdf
- Transportation insecurity cohort (EnROUTE; 115,982 patients): https://pmc.ncbi.nlm.nih.gov/articles/PMC12342063/
- Complex patchwork review (scale, hospital days, best practices): https://pmc.ncbi.nlm.nih.gov/articles/PMC10561812/
- Lived experience (missed-treatment rates): https://pmc.ncbi.nlm.nih.gov/articles/PMC13089766/ ; UC Davis 2026: https://health.ucdavis.edu/news/headlines/transportation-problems-disrupt-dialysis-care-for-patients-with-kidney-failure/2026/04
- NEMT dialysis share (Delaware LogistiCare data): https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5334728/ ; MACPAC NEMT mandated report: https://www.macpac.gov/wp-content/uploads/2021/06/Chapter-5-Mandated-Report-on-Non-Emergency-Medical-Transportation.pdf
- Session cadence and shifts: https://davita.com/treatment-options/dialysis/in-center-hemodialysis/ ; https://kidney.wustl.edu/treatment-options/in-center-dialysis/ ; https://pmc.ncbi.nlm.nih.gov/articles/PMC12507099/ ; post-treatment recovery description: https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11951241
- Broker practice (standing orders, return legs, NJ brokers): https://deltamedicaltransportation.com/blog/nj-familycare-nemt-complete-guide ; https://medicaideligibilitycalculator.com/free-transportation-for-medicaid-patients/
- Ride-hail pilots and evidence: https://health.usnews.com/health-care/patient-advice/articles/2018-10-10/lyft-and-uber-help-patients-make-it-to-medical-appointments
- DARP with flexible appointment times and return trips: https://arxiv.org/pdf/2105.14472 ; Cordeau & Laporte tabu search: https://ideas.repec.org/a/eee/transb/v37y2003i6p579-594.html

---

## 16. Questions for Ryan (don't block on them; defaults are set)

1. Who are your two teammates and what can each run tonight — a nurse/coordinator for realism, a builder for the solver? (Default: roles in §12.)
2. Model the transport side as an ADA paratransit agency (FTA rules) or a Medicaid NEMT broker (ModivCare-style standing orders)? (Default: NEMT broker whose vehicles follow ADA-style windows and the ±60 rule — it reads true to both rooms.)
3. Are `claude-fable-5-1`, `claude-sonnet-5`, and Haiku 4.5 all enabled on the event credits, and do you want structured-output support on Fable 5.1 checked first thing? (Default: yes, at CP0.)
4. Windows laptop tonight? (Default: yes — every hook is a Python script; if you're on a Mac, they still work.)
5. Do you want the FHIR `Appointment` export as the stretch goal to tie into Anthropic's FHIR skill story, or the Sonnet-driven broker party for a bigger on-camera "negotiation" moment? (Default: FHIR export — it's one file and it films.)
