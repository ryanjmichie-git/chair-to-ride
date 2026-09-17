# Tonight's runbook

## Prerequisites
- `uv` on PATH (installs and runs the project venv).
- GNU make: Git Bash does not ship one, so `winget install GnuWin32.Make` or equivalent.
- Python >= 3.11 on PATH as `python` (hooks and `scripts/` run under it), and `git`.

## Before opening Claude Code
```
make setup && make models && make synth && make baseline
uv run python scripts/check_models.py
```
Start `claude` from the repo root, run `/hooks`, confirm **7 hooks** are registered. Confirm `/rename` and `/model` exist with `/help` — API surface can drift between builds.

## Roles (worktree split, merge at each CP)
- **A (Ryan)** — orchestrator, cost meter, worktree `orchestrator`.
- **B (clinical/transport teammate)** — `rules.yaml`, policy texts, note realism, judge calibration, demo narration; worktree `docs/policies`.
- **C (builder)** — solver + verifier under A's spec; worktree `solver`.

## Session table (one Claude Code session per checkpoint)
| Step | Command |
|---|---|
| 1 | `/clear` |
| 2 | `/rename cpN-writer` |
| 3 | `/kickoff cpN` (spec check → plan mode → build) |
| 4 | `/review` (fresh session or `/rename cpN-reviewer`) |
| 5 | `/commit` |

Writer (A) implements the spec; reviewer (a fresh session running `/review`) sees only the diff and the spec, reports gaps, never fixes. A pastes findings back, fixes, re-reviews. `/lesson` on every misunderstanding.

## Emergency cut
If **CP1 slips past T+2:00**, drop the mediator loop and run `run_direct.py`: local-search solver (no LLM) → `verify` gate → one Fable 5.1 call for triage + summaries → Sonnet for rider explanations. Still a real before/after number, a queue, and a cost meter on screen — lose only the live negotiation.

## Checkpoints
See `specs/INDEX.md` for the CP0–CP5 table and their specs.
