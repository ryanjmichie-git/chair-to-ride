# Chair-to-Ride

An agent re-times a dialysis unit's chair schedule against a paratransit manifest. SYNTHETIC DATA only; never invoke real health-privacy regulation by name.

## Commands
- `make setup` — `uv sync` the venv (Python 3.12).
- `make models` — regenerate Pydantic models from `specs/schemas/`.
- `make synth` — generate synthetic data (seed 42) into `data/synthetic/42/`.
- `make baseline` — print before-metrics for the synthetic day.
- `make test` — run the full test suite.
- `make gate` — run the eval gate (`evals/run_evals.py --gate`).
- `make demo` — run the demo.
- `/kickoff [cpN]` — spec-check, plan mode, implement, then `/review` and `/commit`.
- `/review` — reviewer subagent reports gaps vs. the active spec.
- `/run-demo` — run `make demo` and summarise the run's metrics.
- `/run-evals [--gate|--full|--judge-only]` — run evals, summarise failures.
- `/lesson "<one line>"` — record a lesson; ask if it should become a hook.
- `/commit` — lint + test, then commit `cpN: <what>`; never push.

## Rules of engagement
- Plan mode for any change touching > 1 file under `src/c2r/` or any file under `prompts/`.
- `/clear` between unrelated tasks; after two failed corrections, clear and rewrite the prompt.
- No checkpoint starts without `/kickoff cpN` passing the spec check.
- Manual accept for `src/c2r/verify.py` and `prompts/` edits; auto mode only for `viz/` and `docs/`.
- Diffs ≤ 400 changed lines in `src/`.
- Every constraint lives in `verify.py`, never in a prompt.
- Numbers come from Python; the model chooses, it never computes.
- Prompts are versioned files; never edit one in place once it carries `eval_result`.
- Hooks are Python, paths via `pathlib`; `uv run` for project code; hooks and `scripts/` run under system `python`.
- Load the `domain-rules` skill before touching solver, verify, parties, or `rules.yaml`.

@specs/INDEX.md

# Lessons
- verify() derives every bound (start, ready, chair band, load) from the roster and the stop sequence, never from a window or load_after field the solver wrote into the manifest.
- Negotiable anchors (requested_time) are compared against the baseline, never the candidate, in verify and in the parties; the builder only sets a request for will-call riders.
