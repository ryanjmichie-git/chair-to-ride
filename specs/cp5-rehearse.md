# CP5 — Rehearse

## Goal
Two clean timed dry runs and a backup recording, ready for the 3-minute demo call.

## Files
- `docs/demo_script.md` — final version (written by the `demo-narrator` subagent from `runs/` and the handoff's demo-beat section).
- `docs/backup.mp4` — screen recording of one clean end-to-end run.

## Out of scope
Any further code change to `src/c2r/` (frozen at CP4 except `viz/`).

## Definition of done
- Two timed dry runs of `make demo` complete inside the 3-minute demo window, back to back.
- `docs/backup.mp4` exists and plays a full clean run (before → perturbation → after → explanations).
- `docs/demo_script.md` matches what was actually said in the second dry run.
- Emergency-cut plan (`run_direct.py`, no live negotiation) is understood by whoever is on stage, in case CP1 had slipped past T+2:00 earlier in the night.

## Verification command
```
make demo
make demo
```
Time both runs; confirm `docs/backup.mp4` and `docs/demo_script.md` are present and current.

## PR checklist
- [ ] C1 — test output pasted
- [ ] C5 — reviewer findings attached and addressed, or waived with reason
- [ ] C8 — a lesson or a hook added if a misunderstanding caused a bug
- [ ] K2 — diff ≤ 400 changed lines in `src/`
