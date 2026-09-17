# Demo runbook (3 minutes on stage, 10 minutes of set-up)

Written for the person driving the terminal. Every command runs from the repo root in
PowerShell. Numbers in brackets are what the same commands produced on 2026-09-17; read the
live ones off the screen, do not quote these.

## 10 minutes before: pre-flight (about $0.85, 3 minutes of runtime)

1. Open two terminals in `C:\Users\RyanMichie\chair-to-ride`, font large. Terminal A runs the
   demo; terminal B shows files.
2. Terminal A, one rehearsal so the venue network is proven and the artefacts are fresh:
   ```
   make demo
   ```
   Expect `mediate` (the day run, 57-89 s, prints each turn and ends with metrics) then
   `perturb` (V3 down at 13:40, 14-25 s, ends with `0 violations`). If either fails on the
   network, see "If the API is down" below and do not retry more than once.
3. Terminal A, the notes and the judge for both runs (about 90 s, about $0.30):
   ```
   make explain
   make judge
   ```
4. Render the re-plan timeline and open both timelines in the browser, each in its own tab:
   ```
   uv run python -m c2r.viz.timeline runs/cp2
   uv run python -m c2r.viz.timeline runs/cp3
   start runs\cp2\timeline.html
   start runs\cp3\timeline.html
   ```
   Tab 1 = the day (before/after), tab 2 = the re-plan (heading names the event).
5. Terminal B, three commands, one per beat (tested 2026-09-17; `explanations.json` is 175 KB,
   so the second line prints one note instead of the whole file):
   ```
   type runs\cp2\review_queue.json
   python scripts\show_note.py runs\cp2
   python scripts\show_note.py runs\cp3 E16d
   type cost_report.md
   ```
   These work in cmd and PowerShell alike. The dispatcher note `E16d` is the breakdown story
   in one paragraph: P16's ride lost its van at 13:40, decide by 15:11 or hold for will-call.
   `cost_report.md` only changes when you run `make cost-report`; do that after the pre-flight
   runs if you want tonight's dollars in it.
6. Clear terminal A (`cls`). Say the words "synthetic data" once, on screen and aloud; the
   banner prints it on every run.

## The 3 minutes

| Clock | Do | Say (one line) |
|---|---|---|
| 0:00 | Browser tab 1, scroll to the "before" Gantt: 12 chair rows, 5 van rows, red wait bars. | "After four hours on a machine these riders wait about seventy minutes for a van booked days ago. Nobody re-times the chairs and the rides together. All of this is synthetic data." [before: mean 70.2 min, p90 131] |
| 0:30 | Terminal A: `make mediate` (runs live, 57-89 s; let it scroll). | "Chair-to-Ride reads both rulebooks and both schedules, then negotiates chair times against pickup windows inside the sixty-minute ADA rule and the nurse's notes. The model chooses; deterministic code counts; nothing is applied without a zero-violation check." |
| 1:30 | When it ends, point at the closing metrics line, then `type runs\cp2\review_queue.json`. | "Mean wait from seventy to under two minutes, p90 from 131 to 6, zero chair conflicts. The riders it could not fix inside the rules it queued for a person, with the reason and a draft message." [today: 4 flagged before, 1-2 after] |
| 1:50 | Terminal A: `make perturb`. Browser tab 2 once it ends. | "Now Van 3 dies at 1:40. Same rules, same receipts. Every return on that van is re-homed or handed to the dispatcher, and it finishes in about fifteen seconds." [today: 13.3-25 s, P15f to V4, P29f to V2, P16f held] |
| 2:20 | Terminal B: `type runs\cp2\explanations.json` (scroll to one rider note), then `type cost_report.md`. | "Every rider gets a plain-English note whose numbers are checked against the ledger. Every decision is in a ledger a charge nurse can audit. The run cost under a dollar on Fable 5.1, with about ninety percent of the prompt read from cache." [day $0.72, re-plan $0.11, cache read 85-94 %] |
| 2:50 | Terminal A: `make gate` output line from earlier, or say it. | "Three hundred and six checks pass in half a minute: invariants, the golden judge set twelve of twelve, cost and runtime receipts. The chair schedule and the ride schedule finally talk to each other." |

`make demo` runs both steps back to back if you prefer one command; splitting them gives you
the pause at 1:30 to show the queue.

## If the API is down (no network, key rejected, or a turn hangs past 30 s)

Same commands, offline scripted mediator, identical screens, $0:
```
make mediate-fake
make perturb-fake
uv run python -m c2r.explain runs/cp2-fake --fake
uv run python -m c2r.viz.timeline runs/cp2-fake
uv run python -m c2r.viz.timeline runs/cp3-fake
```
Say "this is the offline replay of the same run" and carry on. The day run cannot hang: the
harness force-finishes at 90 s and the re-plan at 30 s, and both always end with a verified
schedule.

## Things that bite

- The day run's length is the model's choice: 57 s and 71 s on this seed today, 89 s on another
  seed. Start `make mediate` no later than 0:30.
- `make timeline` still points at `runs/cp1`; use the two `python -m c2r.viz.timeline` lines.
- `make demo` overwrites `runs/cp2` and `runs/cp3`; that is fine, they are regenerated artefacts.
- Do not run `make full`; it spends money and takes ten minutes.
- `src/c2r` is frozen. If something breaks, switch to the fake run; do not edit code on stage.
