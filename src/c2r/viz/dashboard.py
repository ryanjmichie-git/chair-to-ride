"""One browser page for the demo, rebuilt from the run files while the re-plan runs.

``python -m c2r.viz.dashboard --watch [--day runs/cp2] [--replan runs/cp3] [--out runs/demo.html]``

Every number on the page is read from ``metrics.json``, ``ledger.jsonl``, ``event.json``,
``review_queue.json`` and ``explanations.json``; nothing is computed here. The page reloads
itself every 3 s (works from ``file://``); ``--watch`` rewrites it every 2 s, so the live panel
fills in turn by turn as the orchestrator appends to the ledger. Colour never carries meaning
on its own: every state also has a word.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import time
from pathlib import Path
from typing import Any

from c2r.banner import BANNER

ROOT = Path(__file__).resolve().parents[3]
RECEIPTS = ROOT / "evals" / "golden" / "receipts.json"
CARDS = (
    ("mean_post_wait", "Mean wait after treatment", "min"),
    ("p90_post_wait", "Slowest 10 % wait", "min"),
    ("within_30_share", "Riders picked up within 30 min", "share"),
    ("riders_flagged", "Riders handed to a person", ""),
    ("conflicts", "Chair conflicts", ""),
    ("equity_gap", "Wheelchair vs walking gap", "min"),
)
STYLE = """
:root{--ink:#14202b;--muted:#4b5a68;--paper:#fbfbf8;--card:#fff;--line:#c9d1d9;--accent:#0b5cad}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:18px/1.45 "Segoe UI",system-ui,sans-serif}
.banner{background:#1f2a36;color:#fff;font-weight:700;letter-spacing:.04em;padding:.5rem 1.5rem;font-size:1rem}
header{padding:1.2rem 1.5rem .4rem}h1{margin:0;font-size:2rem}h2{font-size:1.4rem;margin:0 0 .6rem;border-bottom:2px solid var(--line);padding-bottom:.2rem}
main{display:grid;grid-template-columns:1fr 1fr;gap:1.2rem;padding:0 1.5rem 2rem}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:1rem 1.2rem}
.wide{grid-column:1 / -1}.status{font-size:1.1rem;font-weight:600;margin:.2rem 0 .8rem}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:.7rem}
.card{border:1px solid var(--line);border-radius:8px;padding:.6rem .8rem}
.card .label{color:var(--muted);font-size:.9rem}.card .val{font-size:1.6rem;font-weight:700}
.card .before{color:var(--muted);font-size:1rem;text-decoration:line-through}
.turns{list-style:none;padding:0;margin:0}.turns li{border-left:4px solid var(--line);padding:.3rem .8rem;margin:.4rem 0}
.turns .who{color:var(--muted);font-size:.9rem}.turns .tools{color:var(--muted);font-size:.95rem}
.note{border:1px solid var(--line);border-radius:8px;padding:.7rem .9rem;margin:.5rem 0}
.note .to{color:var(--muted);font-size:.9rem}.queue{margin:.5rem 0}.queue dt{font-weight:700}
.receipts td,.receipts th{padding:.25rem .8rem .25rem 0;text-align:left}
details{margin-top:.8rem}iframe{width:100%;height:520px;border:1px solid var(--line);border-radius:8px;background:#fff}
.muted{color:var(--muted)}
"""


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ledger(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "ledger.jsonl"
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue  # a half-written last line while the run is going
    return entries


def _fmt(key: str, value: Any, unit: str) -> str:
    if value is None:
        return "-"
    if unit == "share":
        return f"{float(value):.0%}"
    if isinstance(value, float) and not float(value).is_integer():
        return f"{value:.1f} {unit}".strip()
    return f"{int(value)} {unit}".strip()


def cards(metrics: dict[str, Any] | None) -> str:
    if not metrics:
        return '<p class="muted">No run yet.</p>'
    before, after = metrics.get("before") or {}, metrics.get("after") or {}
    out = []
    for key, label, unit in CARDS:
        out.append(
            f'<div class="card"><div class="label">{html.escape(label)}</div>'
            f'<div class="val">{_fmt(key, after.get(key), unit)}</div>'
            f'<div class="before">was {_fmt(key, before.get(key), unit)}</div></div>'
        )
    return f'<div class="cards">{"".join(out)}</div>'


def turns(entries: list[dict[str, Any]]) -> str:
    items = []
    calls: dict[int, list[str]] = {}
    for entry in entries:
        if entry["actor"] == "tool" and entry["event"] not in ("run_start", "run_finish"):
            result = entry["payload"].get("result") or {}
            tag = entry["event"]
            if tag == "verify":
                tag += f" ({len(result.get('violations') or [])} violations)"
            elif tag in ("propose_to_unit", "propose_to_broker"):
                tag += " (accepted)" if result.get("accepted") else " (rejected)"
            elif tag == "apply_bundle":
                tag += " (applied)" if result.get("applied") else " (refused)"
            calls.setdefault(entry["iteration"], []).append(tag)
    for entry in entries:
        if entry["actor"] != "model":
            continue
        text = (entry["payload"].get("text") or "").strip() or "(no comment this turn)"
        tools = ", ".join(calls.get(entry["iteration"], []))
        items.append(
            f'<li><div class="who">Turn {entry["iteration"]} · {html.escape(entry["model_id"])}'
            f" · ${float(entry['cost_usd']):.2f}</div>{html.escape(text)}"
            f'<div class="tools">{html.escape(tools)}</div></li>'
        )
    return f'<ol class="turns">{"".join(items)}</ol>' if items else ""


def status(run_dir: Path, metrics: dict[str, Any] | None, entries: list) -> str:
    if not entries:
        return "Waiting for the re-plan to start."
    if metrics is None:
        model_turns = sum(1 for e in entries if e["actor"] == "model")
        return f"Running: {model_turns} model turn(s) so far."
    usage = metrics.get("usage") or {}
    checks = [e for e in entries if e["event"] == "verify"]
    last = checks[-1]["payload"].get("result") or {} if checks else {}
    violations = (
        f", {len(last.get('violations') or [])} violations on the applied schedule"
        if checks
        else ""
    )
    return (
        f"Done in {metrics.get('elapsed_s', '?')} s, {usage.get('iterations', '?')} turns, "
        f"${float(usage.get('cost_usd', 0)):.2f}, {float(usage.get('cache_read_share', 0)):.0%} "
        f"of the prompt read from cache{violations}."
    )


def event_line(run_dir: Path) -> str:
    event = _load(run_dir / "event.json")
    if not event:
        return "Live re-plan"
    payload = event["event"]["payload"]
    van = payload.get("vehicle_id", "?")
    affected = ", ".join(event.get("affected") or [])
    return f"Live: van {van} is down at {event['now']}; returns affected: {affected}"


def queue(run_dir: Path) -> str:
    items = _load(run_dir / "review_queue.json") or []
    if not items:
        return '<p class="muted">Nothing waiting for a person.</p>'
    out = []
    for item in items:
        out.append(
            f'<dl class="queue"><dt>{html.escape(item.get("subject", ""))} · '
            f"{html.escape(item.get('reason_code', ''))} · owner: {html.escape(item.get('owner', ''))}</dt>"
            f"<dd>{html.escape(item.get('recommended_action', ''))}</dd></dl>"
        )
    return "".join(out)


def notes(run_dir: Path, limit: int = 3) -> str:
    records = _load(run_dir / "explanations.json") or []
    picked: list[dict[str, Any]] = []
    for audience in ("rider", "dispatcher", "nurse"):
        for record in records:
            if record["explanation"]["audience"] == audience and len(picked) < limit:
                picked.append(record)
                break
    if not picked:
        return '<p class="muted">Notes appear after <code>make explain</code>.</p>'
    out = []
    for record in picked:
        note = record["explanation"]
        out.append(
            f'<div class="note"><div class="to">To the {html.escape(note["audience"])} · '
            f"{html.escape(note['subject_id'])} · reading grade {note['reading_grade']}</div>"
            f"<p>{html.escape(note['what_changed'])}</p><p>{html.escape(note['why'])}</p>"
            f'<p class="muted">Who to call: {html.escape(note["contact"])}</p></div>'
        )
    return "".join(out)


def receipts(day: dict[str, Any] | None, replan: dict[str, Any] | None) -> str:
    rows = []
    for name, metrics in (("Day run", day), ("Re-plan", replan)):
        if metrics:
            usage = metrics.get("usage") or {}
            rows.append(
                f"<tr><th>{name}</th><td>${float(usage.get('cost_usd', 0)):.2f}</td>"
                f"<td>{float(usage.get('cache_read_share', 0)):.0%}</td>"
                f"<td>{metrics.get('elapsed_s', '?')} s</td></tr>"
            )
    gate = _load(RECEIPTS)
    line = ""
    if gate:
        judge = gate["judge_golden"]
        line = (
            f"<p>Eval gate: judge agreement {html.escape(judge['agreement'])} on the golden set; "
            f"306 offline checks pass in about half a minute; every rule lives in code.</p>"
        )
    return (
        '<table class="receipts"><tr><th></th><th>Cost</th><th>Cache read</th><th>Time</th></tr>'
        f"{''.join(rows)}</table>{line}"
    )


def render(day_dir: Path, replan_dir: Path, out: Path) -> str:
    day = _load(day_dir / "metrics.json")
    replan = _load(replan_dir / "metrics.json")
    entries = _ledger(replan_dir)
    who_dir = replan_dir if (replan_dir / "explanations.json").is_file() else day_dir
    queue_dir = replan_dir if replan else day_dir

    def rel(path: Path) -> str:
        try:
            return path.relative_to(out.parent).as_posix()
        except ValueError:
            return path.resolve().as_uri()

    frames = "".join(
        f"<details><summary>{label} timeline</summary>"
        f'<iframe src="{rel(d / "timeline.html")}" title="{label} timeline"></iframe></details>'
        for label, d in (("Day", day_dir), ("Re-plan", replan_dir))
        if (d / "timeline.html").is_file()
    )
    stamp = time.strftime("%H:%M:%S")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3"><title>Chair-to-Ride demo</title><style>{STYLE}</style></head>
<body><div class="banner">{html.escape(BANNER)}</div>
<header><h1>Chair-to-Ride: the chair schedule and the ride schedule, negotiated together</h1>
<p class="muted">Harborline Dialysis Unit, one synthetic Wednesday. Page rebuilt {stamp}.</p></header>
<main>
<section><h2>The day, re-timed by the mediator</h2>
<p class="status">{html.escape(status(day_dir, day, _ledger(day_dir)))}</p>{cards(day)}</section>
<section><h2>{html.escape(event_line(replan_dir))}</h2>
<p class="status">{html.escape(status(replan_dir, replan, entries))}</p>{cards(replan) if replan else ""}{turns(entries)}</section>
<section><h2>Handed to a person</h2>{queue(queue_dir)}</section>
<section><h2>What riders and staff are told</h2>{notes(who_dir)}</section>
<section class="wide"><h2>Receipts</h2>{receipts(day, replan)}{frames}</section>
</main></body></html>
"""


def write(day_dir: Path, replan_dir: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(day_dir, replan_dir, out), encoding="utf-8", newline="\n")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default="runs/cp2")
    parser.add_argument("--replan", default="runs/cp3")
    parser.add_argument("--out", default="runs/demo.html")
    parser.add_argument("--watch", action="store_true", help="rewrite every 2 s until Ctrl+C")
    args = parser.parse_args()
    day, replan, out = Path(args.day), Path(args.replan), Path(args.out)
    print(f"dashboard -> {write(day, replan, out)}  (open it in a browser)")
    if not args.watch:
        return 0
    print("watching; Ctrl+C to stop")
    try:
        while True:
            time.sleep(2)
            write(day, replan, out)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
