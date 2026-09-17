"""Shared stdlib helpers for the Chair-to-Ride Claude Code hooks."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, NoReturn


def read_event() -> dict[str, Any]:
    try:
        event = json.load(sys.stdin)
    except (OSError, ValueError):
        sys.exit(0)
    if not isinstance(event, dict):
        sys.exit(0)
    return event


def repo_root() -> Path:
    override = os.environ.get("C2R_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def rel_path(event: dict[str, Any]) -> str | None:
    tool_input = event.get("tool_input")
    raw = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not raw:
        return None
    root = repo_root()
    target = Path(str(raw))
    if not target.is_absolute():
        target = root / target
    try:
        return target.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None


def frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}
    fields: dict[str, str] = {}
    index = 1
    while index < end:
        line = lines[index]
        index += 1
        key, sep, value = line.partition(":")
        if not sep or not key.strip() or line[:1].isspace():
            continue
        value = value.strip().strip("\"'")
        if not value and index < end and lines[index][:1].isspace() and lines[index].strip():
            value = "<block>"
            while index < end and (lines[index][:1].isspace() or not lines[index].strip()):
                index += 1
        fields[key.strip()] = value
    return fields


def glob_match(path: str, glob: str) -> bool:
    parts: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            parts.append("(.*/)?")
            i += 3
        elif glob.startswith("**", i):
            parts.append(".*")
            i += 2
        elif glob[i] == "*":
            parts.append("[^/]*")
            i += 1
        else:
            parts.append(re.escape(glob[i]))
            i += 1
    return re.fullmatch("".join(parts), path) is not None


def deny(reason: str) -> NoReturn:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    print(reason, file=sys.stderr)
    sys.exit(2)


def block(reason: str) -> NoReturn:
    print(json.dumps({"decision": "block", "reason": reason}))
    print(reason, file=sys.stderr)
    sys.exit(2)
