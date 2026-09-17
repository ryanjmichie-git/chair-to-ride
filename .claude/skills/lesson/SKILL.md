---
name: lesson
description: Record a one-line lesson to CLAUDE.md and consider whether it should be a hook instead.
argument-hint: "\"<one line>\""
allowed-tools:
  - Bash
---

# /lesson

1. Run `python scripts/add_lesson.py "$ARGUMENTS"` and show its result (it appends under `# Lessons` in `CLAUDE.md`, or refuses at 15 lessons).
2. Ask one question: is the lesson mechanical — a path, a command, a pattern a script could check? If yes, propose the hook that would enforce it instead of relying on the CLAUDE.md line (H3).
