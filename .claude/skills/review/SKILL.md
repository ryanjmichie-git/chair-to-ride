---
name: review
description: Diff the working tree against the active checkpoint spec and get the reviewer subagent's gap report. Never fixes anything itself.
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - Agent
---

# /review

1. Run `git diff HEAD --stat` and `git diff HEAD`.
2. Read `specs/INDEX.md` to find the `active` checkpoint and its spec path.
3. Launch the `reviewer` subagent with the `Agent` tool (`subagent_type: reviewer`), passing it the diff and the spec path.
4. Print the reviewer's findings in the PR-checklist form (`specs/TEMPLATE.md`'s four items). Do not fix anything — that is the writer session's job.
