"""PreToolUse (Bash|PowerShell): refuse destructive commands outside a temp or scratchpad root."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import deny, read_event

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*[rR]|-[rR]\b|--recursive\b)"),
        "recursive rm",
    ),
    (re.compile(r"\bRemove-Item\b[^|;]*-Recurse", re.IGNORECASE), "Remove-Item -Recurse"),
    (
        re.compile(r"\bgit\s+push\b[^|;]*(--force-with-lease\b|--force\b|(?<=\s)-f\b)"),
        "git push --force",
    ),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "git reset --hard"),
    (re.compile(r"\bgit\s+clean\b[^|;]*-[a-zA-Z]*f"), "git clean -f"),
    (re.compile(r"\bgit\s+checkout\s+--\s+\."), "git checkout -- ."),
    (re.compile(r"\bgit\s+branch\s+-D\b"), "git branch -D"),
]
RAW_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"(\b(mkdir|touch|cp|mv|New-Item|Copy-Item|Move-Item)\b.*|>>?\s*[\"']?)"
            r"[^\s\"';|]*data[/\\]real",
            re.IGNORECASE,
        ),
        "creates data/real",
    ),
]
QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
SEPARATORS = re.compile(r"&&|\|\||;|\|")
DASH_C = re.compile(r"(?:^|\s)-c\s+(.+)$")


def _normalise(path: str) -> str:
    drive = re.match(r"^/([a-zA-Z])/(.*)$", path)
    if drive:
        path = f"{drive.group(1).upper()}:/{drive.group(2)}"
    return os.path.normcase(os.path.normpath(path))


def _safe_roots(event: dict[str, object]) -> list[str]:
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.environ.get("TEMP", ""),
        os.path.join(local, "Temp") if local else "",
        str(event.get("scratchpad_dir") or ""),
    ]
    return [_normalise(os.path.expandvars(c)) for c in candidates if c]


def _segments(command: str) -> list[tuple[str, str]]:
    masked = QUOTED.sub(lambda m: m.group(0)[0] * 2 + " " * (len(m.group(0)) - 2), command)
    spans: list[tuple[int, int]] = []
    start = 0
    for separator in SEPARATORS.finditer(masked):
        spans.append((start, separator.start()))
        start = separator.end()
    spans.append((start, len(command)))
    return [(command[a:b], masked[a:b]) for a, b in spans]


def _inner(segment: str) -> str:
    match = DASH_C.search(segment)
    return match.group(1) if match else ""


def _rm_targets_safe(segment: str, roots: list[str]) -> bool:
    match = re.search(r"\brm\b(.*)$", segment)
    if not match or not roots:
        return False
    targets = [t.strip("\"'") for t in match.group(1).split() if not t.startswith("-")]
    if not targets:
        return False
    return all(
        any(_normalise(os.path.expandvars(os.path.expanduser(t))).startswith(r) for r in roots)
        for t in targets
    )


def main() -> int:
    event = read_event()
    command = (event.get("tool_input") or {}).get("command") or ""
    if not command:
        return 0
    roots = _safe_roots(event)
    for raw, scan in _segments(command):
        inner = _inner(raw)
        found = [label for pattern, label in PATTERNS if pattern.search(scan) or pattern.search(inner)]
        found += [label for pattern, label in RAW_PATTERNS if pattern.search(raw)]
        hits = list(dict.fromkeys(found))
        if not hits:
            continue
        if hits == ["recursive rm"] and _rm_targets_safe(raw, roots):
            continue
        deny(f"blocked destructive command ({', '.join(hits)}); ask before running it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
