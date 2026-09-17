# CP2 — Mediator loop

## Goal
A live agent run: the mediator (Fable 5.1) chooses among solver bundles, negotiates with both parties, verifies, applies, and writes the ledger — on camera, in the terminal.

## Files
- `src/c2r/orchestrator.py` — the propose → verify → score loop (§6), 8 strict tools, cache blocks A–C stable across iterations.
- `src/c2r/tools.py` — tool schemas; strips any numeric claim from free text into the ledger as "unverified" (K4).
- `src/c2r/ledger.py` — `ledger.jsonl` writer; `review_queue.json` writer.
- `prompts/mediator.v1.md` — system prompt, block A (laws + decision policy + ledger format, ≤ 900 tokens).
- `evals/invariants/test_*.py` — I16–I20.

## Out of scope
Perturbation events (CP3), explanations and judge (CP3), eval-gate freeze (CP4).

## Note
Re-check at CP2: the API docs read today say effort is `effort: {level}` per message, not `output_config.effort`, and adaptive thinking is always on for Fable 5.1 — confirm with `scripts/check_models.py` before writing `llm.py`.

## Definition of done
- A single run completes in ≤ 90 s wall clock, ≤ 12 iterations.
- `ledger.jsonl` and `review_queue.json` are produced and non-empty for a scenario with residue.
- Cache-read share ≥ 0.80 from iteration 2 (I20).
- Every `apply_bundle` in the ledger is preceded by a `verify` with the same hash and zero violations (I19).
- I16–I20 all green.

## Verification command
```
uv run pytest evals/invariants -q
time uv run python -m c2r.orchestrator data/synthetic/42
```

## PR checklist
- [ ] C1 — test output pasted
- [ ] C5 — reviewer findings attached and addressed, or waived with reason
- [ ] C8 — a lesson or a hook added if a misunderstanding caused a bug
- [ ] K2 — diff ≤ 400 changed lines in `src/`
