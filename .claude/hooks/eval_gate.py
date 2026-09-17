"""Stop: refuse to end the turn until the eval gate passes for the current source digest."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import block, read_event, repo_root

TRACKED = (
    "src",
    "evals",
    "specs",
    "config",
    "prompts",
    "scripts",
    ".claude",
    "CLAUDE.md",
    "Makefile",
    "pyproject.toml",
)


def _digest(root: Path) -> str:
    files: list[Path] = []
    for name in TRACKED:
        entry = root / name
        if entry.is_file():
            files.append(entry)
        elif entry.is_dir():
            files += [
                p for p in entry.rglob("*") if p.is_file() and "__pycache__" not in p.parts
            ]
    sha = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        sha.update(path.relative_to(root).as_posix().encode("utf-8"))
        sha.update(path.read_bytes())
    return sha.hexdigest()


def main() -> int:
    event = read_event()
    if event.get("stop_hook_active"):
        return 0
    root = repo_root()
    if not (root / "evals" / "run_evals.py").is_file():
        return 0
    digest = _digest(root)
    marker = root / "runs" / ".gate_ok"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == digest:
        return 0
    try:
        proc = subprocess.run(
            ["uv", "run", "python", "evals/run_evals.py", "--gate"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0
    output = proc.stdout + proc.stderr
    if proc.returncode == 0:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(digest + "\n", encoding="utf-8")
        return 0
    lines = output.splitlines()
    summary = next((line for line in reversed(lines) if line.startswith("GATE ")), "GATE FAIL")
    block(summary + "\n" + "\n".join(lines[-30:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
