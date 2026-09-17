"""PreToolUse (Edit|Write): block writes under data/real/ and any PHI in data/, runs/, prompts/."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import deny, read_event, rel_path, repo_root

SCANNED = ("data/", "runs/", "prompts/")


def main() -> int:
    event = read_event()
    rel = rel_path(event)
    if rel is None:
        return 0
    if rel.startswith("data/real/"):
        deny(f"{rel}: data/real/ must never exist; this repo is synthetic-only")
    if not rel.startswith(SCANNED):
        return 0
    tool_input = event.get("tool_input") or {}
    text = tool_input.get("content") or tool_input.get("new_string") or ""
    sys.path.insert(0, str(repo_root() / "src"))
    from c2r.phi import find_phi

    hits = find_phi(str(text))
    if hits:
        deny(f"{rel}: PHI pattern matched ({', '.join(hits)}); use synthetic identifiers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
