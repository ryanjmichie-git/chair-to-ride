# CP3 — Perturb + explain + judge

## Goal
The full 3-minute demo: a live disruption, a re-plan, plain-language explanations, and a judge score.

## Files
- `src/c2r/perturb.py` — replays an `events.jsonl` entry against the running state and re-plans.
- `prompts/explainer.v1.md` — Sonnet 5 system prompt, grade ≤ 8 reading level, cites `ledger_refs`.
- `prompts/judge.v1.md` — Fable 5.1 (low effort) rubric, strict JSON, 0–2 per dimension (§9.C).
- `evals/data/` additions for the 12-item golden explanation set and the judge calibration file.

## Out of scope
Eval-gate freeze, `--full` suite, rehearsal recording (CP4/CP5).

## Definition of done
- `perturb.py --event vehicle_down --at 13:40` re-plans in ≤ 30 s wall clock; no V3 rider is stranded.
- Explanations reference only facts in `ledger_refs`; any invented number scores accuracy = 0.
- B (clinical teammate) hand-grades 10 explanations; judge/human pass-fail agreement ≥ 8/10, else the rubric is edited before it gates anything.

## Verification command
```
time uv run python -m c2r.perturb --event vehicle_down --at 13:40
uv run python evals/run_evals.py --judge-only
```

## PR checklist
- [ ] C1 — test output pasted
- [ ] C5 — reviewer findings attached and addressed, or waived with reason
- [ ] C8 — a lesson or a hook added if a misunderstanding caused a bug
- [ ] K2 — diff ≤ 400 changed lines in `src/`
