"""Print one plain-English explanation from a run, for the demo screen.

    python scripts/show_note.py runs/cp2          # the first rider note
    python scripts/show_note.py runs/cp2 E30d     # a note by id

Standard library only; runs under the system python from cmd or PowerShell.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    run_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/cp2")
    wanted = sys.argv[2] if len(sys.argv) > 2 else None
    records = json.loads((run_dir / "explanations.json").read_text(encoding="utf-8"))
    record = next(
        (r for r in records if wanted is None or r["explanation_id"] == wanted), records[0]
    )
    note = record["explanation"]
    print("SYNTHETIC DATA")
    print(f"{record['explanation_id']}  to the {note['audience']}  ({note['subject_id']})")
    print()
    print("What changed:", note["what_changed"])
    print("Why:         ", note["why"])
    print("Who to call: ", note["contact"])
    print()
    print(f"reading grade {note['reading_grade']}; every number traced to {note['ledger_refs']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
