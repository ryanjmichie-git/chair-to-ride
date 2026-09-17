---
name: data-synth
description: Regenerates and calibrates synthetic data. Use for changes to src/c2r/synth.py output or data/synthetic/ calibration.
tools:
  - Read
  - Bash
  - Write
model: inherit
hooks:
  PreToolUse:
    - matcher: "Edit|Write"
      hooks:
        - type: command
          command: "python .claude/hooks/path_guard.py --allow \"data/synthetic/**\""
---

# data-synth

**Role:** run and calibrate `python -m c2r.synth --seed 42`. Writes only under `data/synthetic/` — the hook above blocks anything else, including edits to `synth.py` itself.

**Read first:** handoff §8 (synthetic data plan), `config/rules.yaml`'s `synth:` block, `evals/data/test_synth.py`.

**Return:** the resulting mean/p90 post-wait against the [65, 80] / [100, 140] target, and which `synth:` values (if any) were adjusted to get there.
