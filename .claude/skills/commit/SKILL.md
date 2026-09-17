---
name: commit
description: Lint and test, then commit the checkpoint's changes. Never pushes.
allowed-tools:
  - Bash
---

# /commit

1. Run `uv run ruff check .` and `uv run pytest evals/repo -q`. Stop and report if either fails — do not commit.
2. `git add -A`.
3. Commit with message `cpN: <what changed>` (fill in the checkpoint and a short description), with the trailer:
   ```
   Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
   ```
4. Never push.
