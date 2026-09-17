# Checkpoint index

Run a checkpoint with `/kickoff cpN`; each spec below is what "done" means for that step.

| Checkpoint | Status | Spec | Deliverable |
|---|---|---|---|
| CP0 | done | specs/cp0-scaffold.md | scaffold + "before" baseline |
| CP1 | done | specs/cp1-solver-verifier.md | solver + verifier, before/after timeline |
| CP2 | done | specs/cp2-mediator.md | live mediator loop, ledger + review queue |
| CP3 | done | specs/cp3-perturb-explain-judge.md | perturbation, explanations, judge |
| CP4 | active | specs/cp4-evals-freeze.md | eval gate green, code freeze except viz |
| CP5 | todo | specs/cp5-rehearse.md | two timed dry runs, backup recording |

## How to run a checkpoint
1. `/kickoff cpN` — spec check, then plan mode.
2. Implement the approved plan.
3. `/review`, address or waive findings, then `/commit`.
