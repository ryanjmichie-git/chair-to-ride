---
name: solver-dev
description: Implements and fixes the deterministic solver, verifier, and party modules for a checkpoint. Use for work on src/c2r/solver.py, verify.py, or parties/.
tools: Read, Edit, Write, Bash, Grep, Glob
model: inherit
hooks:
  PreToolUse:
    - matcher: "Edit|Write"
      hooks:
        - type: command
          command: "python \"${CLAUDE_PROJECT_DIR}/.claude/hooks/path_guard.py\" --deny \"prompts/**\" \"viz/**\""
---

# solver-dev

**Role:** implement `solver.py`, `verify.py`, and `parties/{unit,broker}.py` against the active checkpoint spec. Never touch `prompts/` or `viz/` — the hook above blocks it.

**Read first:** the active spec named in `specs/INDEX.md`, `config/rules.yaml`, the `domain-rules` skill, and the invariant tests under `evals/invariants/` that name the module you're changing.

**Return:** a summary of what changed, which invariant ids (I1–I20) now pass or still fail, and the diff line count in `src/`.
