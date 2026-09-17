# CP0 — Scaffold + before

## Goal
Stand up the whole repo skeleton and prove the synthetic "before" schedule is realistic enough to build the demo on.

## Files
- `CLAUDE.md`, `KICKOFF.md`, `docs/llms.txt`
- `.claude/settings.json`, `.claude/hooks/*.py`, `.claude/skills/*/SKILL.md`, `.claude/agents/*.md`
- `specs/*` (this file's siblings), `specs/schemas/*.schema.json`
- `config/rules.yaml`, `config/unit_policy.md`, `config/broker_policy.md`
- `src/c2r/{__init__.py, models/, phi.py, synth.py, metrics.py, timeutil.py, banner.py}`
- `data/names.json`, `data/synthetic/42/{unit,roster,manifest,fleet,travel}.json`, `data/synthetic/42/events.jsonl`
- `scripts/{spec_check.py, add_lesson.py, check_models.py}`
- `evals/run_evals.py`, `evals/repo/*`, `evals/data/test_synth.py`, `evals/invariants/__init__.py`
- `prompts/synth_notes.v1.md`
- `Makefile`, `pyproject.toml`

## Out of scope
`solver.py`, `verify.py`, `parties/`, `orchestrator.py`, `tools.py`, `ledger.py`, `viz/timeline.py`, `perturb.py`, and `prompts/mediator.v1.md` / `explainer.v1.md` / `judge.v1.md` — all built at CP1–CP3.

## Definition of done
- `make setup models synth baseline gate` all exit 0.
- Baseline mean post-wait ∈ [65, 80] min, p90 ∈ [100, 140] min (seed 42).
- `/hooks` lists seven hooks (phi_guard, prompt_freeze, danger_guard, pytest_quick, render_timeline, eval_gate, session_brief); CP1 added an eighth, k2_guard.
- Zero PHI-regex matches across `data/`, `runs/`, `prompts/`.
- `CLAUDE.md` ≤ 60 lines; `specs/INDEX.md` has exactly one `active` row (CP0).
- B (clinical teammate) has edited `config/rules.yaml` and read 10 nurse notes in `data/synthetic/42/roster.json`.

## Verification command
```
make setup && make models && make synth && make baseline && make gate
```
Then start `claude` from the repo root and run `/hooks` to confirm seven hooks are registered.

## PR checklist
- [ ] C1 — test output pasted
- [ ] C5 — reviewer findings attached and addressed, or waived with reason
- [ ] C8 — a lesson or a hook added if a misunderstanding caused a bug
- [ ] K2 — diff ≤ 400 changed lines in `src/`
