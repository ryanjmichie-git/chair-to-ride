# Cost report

Generated 2026-09-17 22:06 UTC from every ledger under `runs/` (16 ledgers). SYNTHETIC DATA. Every number below is summed from `ledger.jsonl`, `explain.jsonl`, `judge.jsonl` and `calibration.jsonl`; nothing is typed in.

## Dollars by model

| Model | Calls | Input | Cache read | Cache write | Output | Cache-read share | USD |
|---|---:|---:|---:|---:|---:|---:|---:|
| claude-fable-5-1 | 21 | 59,803 | 214,265 | 36,039 | 6,366 | 69% | $1.42 |
| claude-sonnet-5 | 20 | 82,919 | 0 | 0 | 2,468 | 0% | $0.19 |
| fake-mediator | 109 | 190,500 | 818,000 | 164,000 | 16,730 | 70% | $0.00 |
| **all** | 150 | | | | | | **$1.61** |

## Ledgers

| Run | Role | Model | Effort | Calls | Input | Cache read | Cache write | Output | Cache-read share | USD |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| cp2 | explainer | claude-sonnet-5 | medium | 16 | 67,721 | 0 | 0 | 1,950 | 0% | $0.15 |
| cp2 | mediator | claude-fable-5-1 | medium | 7 | 16 | 166,164 | 32,973 | 2,200 | 83% | $0.56 |
| cp2-fake | mediator | fake-mediator | none | 7 | 12,000 | 181,500 | 34,000 | 1,400 | 80% | $0.00 |
| cp3 | explainer | claude-sonnet-5 | medium | 4 | 15,198 | 0 | 0 | 518 | 0% | $0.04 |
| cp3 | mediator | claude-fable-5-1 | low | 2 | 6 | 48,101 | 3,066 | 437 | 94% | $0.07 |
| cp3-fake | mediator | fake-mediator | none | 3 | 6,000 | 54,500 | 28,000 | 600 | 62% | $0.00 |
| full-fake/42/baseline | explainer | fake-mediator | none | 16 | 24,000 | 0 | 0 | 1,920 | 0% | $0.00 |
| full-fake/42/baseline | judge (batch, half price) | fake-mediator | none | 16 | 32,000 | 0 | 0 | 2,400 | 0% | $0.00 |
| full-fake/42/baseline | mediator | fake-mediator | none | 7 | 12,000 | 181,500 | 34,000 | 1,400 | 80% | $0.00 |
| full-fake/42/vehicle_breakdown | explainer | fake-mediator | none | 4 | 6,000 | 0 | 0 | 480 | 0% | $0.00 |
| full-fake/42/vehicle_breakdown | judge (batch, half price) | fake-mediator | none | 4 | 8,000 | 0 | 0 | 600 | 0% | $0.00 |
| full-fake/42/vehicle_breakdown | mediator | fake-mediator | none | 2 | 4,500 | 26,500 | 26,500 | 400 | 46% | $0.00 |
| full-fake/43/baseline | explainer | fake-mediator | none | 19 | 28,500 | 0 | 0 | 2,280 | 0% | $0.00 |
| full-fake/43/baseline | judge (batch, half price) | fake-mediator | none | 19 | 38,000 | 0 | 0 | 2,850 | 0% | $0.00 |
| full-fake/43/baseline | mediator | fake-mediator | none | 12 | 19,500 | 374,000 | 41,500 | 2,400 | 86% | $0.00 |
| golden-judge | judge | claude-fable-5-1 | low | 12 | 59,781 | 0 | 0 | 3,729 | 0% | $0.78 |

Cache-read share is cache-read tokens over all input tokens (input + cache read + cache write). Batch rows were billed through the Message Batches API at half the listed prices; the fake models cost $0.
