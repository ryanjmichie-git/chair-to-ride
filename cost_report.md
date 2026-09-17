# Cost report

Generated 2026-09-17 22:20 UTC from every ledger under `runs/` (28 ledgers). SYNTHETIC DATA. Every number below is summed from `ledger.jsonl`, `explain.jsonl`, `judge.jsonl` and `calibration.jsonl`; nothing is typed in.

## Dollars by model

| Model | Calls | Input | Cache read | Cache write | Output | Cache-read share | USD |
|---|---:|---:|---:|---:|---:|---:|---:|
| claude-fable-5-1 | 105 | 209,314 | 940,941 | 234,314 | 29,377 | 68% | $4.97 |
| claude-sonnet-5 | 76 | 303,593 | 0 | 0 | 9,418 | 0% | $0.70 |
| fake-mediator | 109 | 190,500 | 818,000 | 164,000 | 16,730 | 70% | $0.00 |
| **all** | 290 | | | | | | **$5.68** |

## Ledgers

| Run | Role | Model | Effort | Calls | Input | Cache read | Cache write | Output | Cache-read share | USD |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| cp2 | explainer | claude-sonnet-5 | medium | 16 | 67,721 | 0 | 0 | 1,950 | 0% | $0.15 |
| cp2 | mediator | claude-fable-5-1 | medium | 7 | 16 | 166,164 | 32,973 | 2,200 | 83% | $0.56 |
| cp2-fake | mediator | fake-mediator | none | 7 | 12,000 | 181,500 | 34,000 | 1,400 | 80% | $0.00 |
| cp3 | explainer | claude-sonnet-5 | medium | 4 | 15,198 | 0 | 0 | 518 | 0% | $0.04 |
| cp3 | mediator | claude-fable-5-1 | low | 2 | 6 | 48,101 | 3,066 | 437 | 94% | $0.07 |
| cp3-fake | mediator | fake-mediator | none | 3 | 6,000 | 54,500 | 28,000 | 600 | 62% | $0.00 |
| full/42/baseline | explainer | claude-sonnet-5 | medium | 16 | 63,509 | 0 | 0 | 2,029 | 0% | $0.15 |
| full/42/baseline | judge (batch, half price) | claude-fable-5-1 | low | 16 | 43,211 | 1,860 | 27,900 | 4,001 | 3% | $0.49 |
| full/42/baseline | mediator | claude-fable-5-1 | medium | 8 | 18 | 198,777 | 33,283 | 2,053 | 86% | $0.57 |
| full/42/vehicle_breakdown | explainer | claude-sonnet-5 | medium | 4 | 14,380 | 0 | 0 | 543 | 0% | $0.03 |
| full/42/vehicle_breakdown | judge (batch, half price) | claude-fable-5-1 | low | 4 | 9,345 | 0 | 7,440 | 1,075 | 0% | $0.12 |
| full/42/vehicle_breakdown | mediator | claude-fable-5-1 | low | 2 | 6 | 48,101 | 3,061 | 427 | 94% | $0.07 |
| full/43/baseline | explainer | claude-sonnet-5 | medium | 19 | 76,542 | 0 | 0 | 2,303 | 0% | $0.18 |
| full/43/baseline | judge (batch, half price) | claude-fable-5-1 | low | 19 | 52,306 | 0 | 35,340 | 5,264 | 0% | $0.61 |
| full/43/baseline | mediator | claude-fable-5-1 | medium | 11 | 24 | 307,009 | 32,644 | 3,155 | 90% | $0.64 |
| full/44/baseline | explainer | claude-sonnet-5 | medium | 17 | 66,243 | 0 | 0 | 2,075 | 0% | $0.15 |
| full/44/baseline | judge (batch, half price) | claude-fable-5-1 | low | 17 | 44,585 | 1,860 | 29,760 | 4,726 | 2% | $0.53 |
| full/44/baseline | mediator | claude-fable-5-1 | medium | 7 | 16 | 169,069 | 28,847 | 2,310 | 85% | $0.52 |
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
