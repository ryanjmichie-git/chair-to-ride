# Session handoff

Updated 2026-09-17 during CP2 (mediator loop). Start a fresh session from here.

## Built this session
CP1 closed with three follow-up commits (k2_guard hook, on-task vehicle minutes, the hold
message wording; details in docs/cp1-decisions.md). Then CP2:

- `src/c2r/ledger.py`: `Ledger` writes one line per run start, model turn, tool call and run
  finish; `read`, `replay` (I18), `usage_summary` (tokens, cache share, dollars).
- `src/c2r/llm.py`: `AnthropicMediator` (Fable 5.1, `output_config.effort` medium, adaptive
  thinking, 30 s per call, two retries, usage and cost) and the offline `FakeMediator`.
- `src/c2r/claims.py`: K4 helpers (`numeric_claims`, `numbers_in`), the 4k-token message budget,
  `state_delta`.
- `src/c2r/tools.py`: eight strict tools, `Session`, `dispatch`; `apply_bundle` refuses without a
  zero-violation verify of that bundle on the current version and both parties' acceptance.
- `src/c2r/orchestrator.py`: blocks A-C once (cache breakpoints), then candidates -> model turn
  -> tools -> ledger; force-finish at the iteration cap or the wall clock; run artefacts and the
  timeline after every apply. `python -m c2r.orchestrator data/synthetic/42 [--out runs/cp2] [--fake]`.
- `src/c2r/solver.py`: `finish_run` (closing pass shared with the mediator), `chain_bundle`
  (up to six accepted moves as one bundle), `write_run(extra)`.
- `prompts/mediator.v1.md`: block A, about 760 tokens, `eval_result: null`.
- `evals/invariants/test_tools.py`, `test_mediator.py` (offline fake run: I16-I19, DoD),
  `test_mediator_live.py` (`llm` marker: I16-I20 on a real run).
- `Makefile`: `mediate`, `mediate-fake`, `test-live`; `demo` now runs `mediate`.
- `docs/cp2-decisions.md`, `docs/llms.txt`, `specs/INDEX.md` (CP1 done, CP2 active).

## Decisions made (details in docs/cp2-decisions.md)
1. Eight tools: the handoff's `write_ledger` is gone; Python writes every ledger entry.
2. Iteration = one model turn (API call); `stop.max_iterations` caps turns.
3. Two-turn protocol per bundle: propose to both + verify in one response, apply in the next.
4. Candidates = top-k single moves + one chained bundle of up to six accepted moves.
5. `verify(bundle_id)` verifies the preview; the hash is bound to the schedule version.
6. K4: numbers in the model's prose not found in any tool result are logged as `unverified`
   and shown as `30 [unverified]`; the prose is kept verbatim.
7. `finish_run` merges model-flagged review items ahead of the computed queue.
8. Offline `FakeMediator` for the gate and as the no-network demo fallback (`--fake`).
9. Four cache breakpoints: blocks A, B, C and the latest user message.
10. The strict-tool grammar rejects integer `minimum`/`maximum`; `k` is clamped in code.
11. Money spent this checkpoint: three `make mediate` runs ($0.62, $0.57, $0.56), one live test
    run (about $0.60), one model ping. About $2.40 in all, against the $20 line in the plan.
12. Reviewer pass: two must-fixes fixed (usage summary event name, `-dirty` git sha), four
    tightenings applied, K4 precision gap recorded for CP3's judge (docs/cp2-decisions.md).

## Artifacts
- `runs/cp2/`: ledger.jsonl, review_queue.json, bundles.json, schedule_before/after.json,
  verify_after.json, metrics.json (with `usage`), timeline.html. Git-ignored; `make mediate`
  regenerates them (live) or `make mediate-fake` (offline, `runs/cp2-fake/`).
- Last live run (seed 42): mean post-wait 70.21 -> 1.71, p90 131 -> 6, equity gap 32.14 ->
  0.89, flagged 4 -> 1 (stretcher P30f), J 1117.15 -> 128.6, 3 chained bundles + 1 closing
  re-time, 7 model turns, 15 tool calls, $0.56, cache-read share 83 %, 56.9 s, 0 violations.
- Runs of the day: 88.6 s / 9 turns (a flag with a sentence as its subject was refused, then a
  separate finish turn), 61.2 s / 8 turns (the model asked for a go-ahead), 56.9 s / 7 turns on
  the prompt as committed.

## Acceptance status
- `uv run pytest evals/invariants -q`: 83 passed, 6 skipped (the live module without a key),
  51 s. `uv run pytest evals/repo -q`: 109 passed.
- `uv run --env-file .env pytest evals/invariants/test_mediator_live.py -q`: 6 passed (70 s) on
  the second prompt; the I16-I20 check functions were then run on the final run's ledger
  (`runs/cp2/ledger.jsonl`) without another API call: all pass.
- `make gate`: 220 passed, GATE PASS, 84.4 s. Over the 60 s K3 budget: the suite grew by the tool and
  mediator tests (about 30 s); CP4 owns the gate time (see what's next).
- `time make mediate`: 56.9 s wall clock, 7 turns, ledger and review queue non-empty.
- Reviewer: one pass; must-fixes fixed, the rest recorded in docs/cp2-decisions.md.

## What's next
1. CP2 is committed (five `cp2:` commits, each under 400 `src/` lines). Run `/kickoff cp3`
   in a fresh session.
2. Gate time: 84 s against a 60 s budget. Candidates: session-scoped fixtures shared across the
   invariant modules, parallelise the `evals/repo` hook tests (they spawn subprocesses). CP4's DoD.
3. Watch the live wall clock: 57-89 s across three runs. No new turn starts inside 15 s of the
   90 s cap, so a run can end forced but never late. If a rehearsal run goes over 80 s, switch
   the default effort to `low` (`--effort low`); the handoff allows it.
4. CP3 starts with `/kickoff cp3`: `perturb.py` replays an event against the running state
   (reuse `tools.Session` + `orchestrator.run` with a seeded state), explanations from the
   ledger entries per subject, the judge.
