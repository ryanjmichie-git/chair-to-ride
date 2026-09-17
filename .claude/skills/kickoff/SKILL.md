---
name: kickoff
description: Start a checkpoint — spec-check it, enter plan mode, implement the approved plan, then hand off to review and commit.
argument-hint: "[cpN]"
allowed-tools:
  - Read
  - Bash
  - Grep
  - Glob
  - EnterPlanMode
  - Skill
---

# /kickoff

1. Resolve `specs/<cpN>-*.md` for the checkpoint named in `$ARGUMENTS` (default: the `active` row in `specs/INDEX.md`).
2. Run `python scripts/spec_check.py <resolved path>`. If it exits non-zero, STOP and show its output verbatim — do not proceed until the spec has all five headers.
3. Enter plan mode. Read the spec, `specs/INDEX.md`, and load the `domain-rules` skill if the checkpoint touches solver, verify, parties, or `rules.yaml`.
4. Produce a plan against the spec's Definition of done. Wait for approval.
5. After approval, implement. Mark the checkpoint's row `active` in `specs/INDEX.md` (and the previous `active` row `done`, if any).
6. Finish by invoking `/review`, then `/commit`.
