# Demo runbook (3 minutes on stage, 10 minutes of set-up)

Written for the person driving the terminal. Every command runs from the repo root in cmd or
PowerShell. The audience sees one browser page (`runs\demo.html`), not the terminal. Numbers in brackets are what the same commands produced on 2026-09-17; read the
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
4. Terminal B, start the live page and open it in the browser, full screen (F11). Leave the
   terminal running; it rewrites the page every 2 s and the page reloads itself every 3 s:
   ```
   make dashboard
   start runs\demo.html
   ```
   The page reads `runs\cp2` (the day) and `runs\cp3` (the re-plan). If `runs\cp3` is from an
   earlier run it already shows "Done"; the panel resets to "Waiting" the moment `make perturb`
   starts, then fills in turn by turn. Both timelines sit at the bottom under "Day timeline" and
   "Re-plan timeline" (click to expand).
5. Backup screens if the browser misbehaves (cmd and PowerShell alike):
   ```
   type runs\cp2eview_queue.json
   python scripts\show_note.py runs\cp2
   python scripts\show_note.py runs\cp3 E16d
   type cost_report.md
   ```
6. Clear terminal A (`cls`). Say the words "synthetic data" once, on screen and aloud; the
   banner prints it on every run.

## The 3 minutes

| Clock | Do | Say (one line) |
|---|---|---|
| 0:00 | Browser, top of the page: banner and "The day" cards (was 70 min, now under 2). | "After four hours on a machine these riders waited about seventy minutes for a van booked days ago. Nobody re-times the chairs and the rides together. This ran a few minutes ago on synthetic data: mean wait from seventy minutes to under two, every rider picked up within thirty." |
| 0:40 | Expand "Day timeline" at the bottom: 12 chair rows, 5 van rows, the wait bars shrink. | "Chair-to-Ride reads both rulebooks and both schedules, then negotiates chair times against pickup windows inside the sixty-minute ADA rule and the nurse's notes. The model chooses; deterministic code counts; nothing is applied without a zero-violation check." |
| 1:10 | Terminal A: `make perturb`. Back to the browser at once. | "Now Van 3 dies at 1:40. Watch the second panel." The panel goes Waiting, then Running with each turn's sentence and tool calls, then Done in about fifteen seconds. "Every return on that van is re-homed or handed to the dispatcher. Same rules, same receipts." [today: 15-25 s, P15f to V4, P29f to V2, P16f held] |
| 2:00 | "Handed to a person" and "What riders and staff are told". | "The rider it could not fix inside the rules goes to a person with the reason and a draft message. Every rider gets a plain-English note whose numbers are checked against the ledger; grade-six reading level." |
| 2:30 | "Receipts". | "The day run cost under thirty cents on Fable 5.1 with ninety-five percent of the prompt read from cache. Three hundred and six checks pass in half a minute, the golden judge set twelve of twelve. The chair schedule and the ride schedule finally talk to each other." |

`make demo` runs both steps back to back if you prefer one command; splitting them gives you
the pause at 1:30 to show the queue.

## If the API is down (no network, key rejected, or a turn hangs past 30 s)

Same commands, offline scripted mediator, identical screens, $0. Point the page at the fake
re-plan (Ctrl+C the watcher in terminal B first):
```
make perturb-fake
uv run python -m c2r.viz.dashboard --watch --replan runs/cp3-fake
```
or the full offline set:
```
make mediate-fake
make perturb-fake
make dashboard-fake
start runs\demo-fake.html
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
