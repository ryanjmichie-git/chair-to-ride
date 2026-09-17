# CP0 deviations from the handoff

Read this before editing `config/rules.yaml` or judging the "before" number. Each line is a
decision made while scaffolding, with the handoff's original value where one existed.

## Synthetic baseline calibration (§8)
| Knob | Handoff | CP0 value | Why |
|---|---|---|---|
| `synth.will_call_count` | 4 | 8 | With real batched routes (no phantom detour minutes), van congestion alone tops out near 54 min mean; will-call carries the tail |
| `synth.will_call_delay_min` | — | 130 | Same |
| `synth.return_vans_per_shift` | — | 1 | One van per shift serves this unit's returns; the rest are assumed busy with other clients |
| `synth.runover_share` | 0.30 | 0.40 | Calibration to mean 65–80 / p90 100–140 on seed 42 |
| `synth.late_start_share` | 0.15 | 0.20 | Same |
| Standing-order window | `end + 30`, ±15 | opens at scheduled ready time, 30 min wide | A ±15 window around end+30 opens before ready time and breaks H6 for every rider; `standing_order_offset_min: 0` |
| `broker.earliest_pickup` | 06:30 (example) | 05:30 | 06:30 cannot coexist with S1 put-on at 06:00 and H12's arrival band |
| `synth.extra_stops_*` | "2–3 stops appended" | removed | Sharing is modelled as real batched stops, so every wait minute is reconstructible from `manifest.json` |

Result on seed 42: mean post-wait 70.21, p90 131, 0 ride-side violations (H6/H8/H9/H10/H12), equity gap 32 (wheelchair riders queue behind the single securement), 4 of 18 riders flagged. Seed 43 lands at p90 154, outside the band; only seed 42 is gated at CP0.

## Schema and model shape (§4, §5)
- `Patient` carries `late_start_min` and `runover_min` so the realism mechanism is data, not a hidden offset.
- `Window` is a Pydantic `RootModel`; read it through `timeutil.window_min`, build it as `Window(root=[...])`.
- `JudgeScore.pass` generates as `pass_`; serialise with `model_dump(by_alias=True)`.
- Models are the package `src/c2r/models/` (generated from `specs/schemas/`), not a single `models.py`.
- `metrics.schema.json` is the VerifyResult metrics block plus `within_30_share` and `riders_flagged`; the run-level before/after/tokens wrapper is CP2.
- `event.payload` and `ledger_entry.payload` are open objects.

## Harness (§7, §11)
- Slash commands are skills under `.claude/skills/<name>/SKILL.md`, invocable as `/<name>`.
- Hook commands use `python "${CLAUDE_PROJECT_DIR}/.claude/hooks/<name>.py"`; a cwd-relative path denies every tool call after any `cd`.
- The gate runs only test directories that contain tests and names them in its summary; `evals/invariants` is gated automatically once CP1 adds tests.
- CP2 must re-check the API parameter names for effort and thinking against `scripts/check_models.py` before writing `llm.py`.
