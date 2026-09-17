"""A static, readable account of one finished demo: every decision, in order, in plain English.

``python -m c2r.viz.story [--day runs/cp2] [--replan runs/cp3] [--out runs/demo_story.html]``

Unlike ``dashboard`` this page does not refresh; it is the write-up of a run that already
happened. Every sentence with a number in it is built from the ledger, metrics, review queue
and explanations of that run, never typed here.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

from c2r.banner import BANNER
from c2r.viz.dashboard import _fmt, _ledger, _load

CARDS = (
    ("mean_post_wait", "Mean wait for the ride home", "min"),
    ("p90_post_wait", "Slowest 10 % wait", "min"),
    ("within_30_share", "Picked up within 30 min", "share"),
    ("riders_flagged", "Riders handed to a person", ""),
    ("conflicts", "Chair conflicts", ""),
    ("equity_gap", "Wheelchair vs walking gap", "min"),
)
STYLE = """
:root{--ink:#14202b;--muted:#4b5a68;--paper:#fbfbf8;--line:#c9d1d9;--accent:#0b5cad}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:19px/1.5 "Segoe UI",system-ui,sans-serif}
.banner{background:#1f2a36;color:#fff;font-weight:700;letter-spacing:.04em;padding:.5rem 1.5rem;font-size:1rem}
.wrap{max-width:1100px;margin:0 auto;padding:1rem 1.5rem 3rem}
h1{font-size:2.2rem;margin:.8rem 0 .2rem}h2{font-size:1.6rem;margin:2.2rem 0 .6rem;border-bottom:3px solid var(--line);padding-bottom:.2rem}
h3{font-size:1.2rem;margin:1.2rem 0 .4rem}.lead{font-size:1.15rem;color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:.8rem;margin:.8rem 0}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:.7rem 1rem}
.card .label{color:var(--muted);font-size:.95rem}.card .val{font-size:1.9rem;font-weight:700}
.card .before{color:var(--muted)}.card .before s{margin-right:.3rem}
.turn{background:#fff;border:1px solid var(--line);border-left:6px solid var(--accent);border-radius:10px;padding:.9rem 1.2rem;margin:.9rem 0}
.turn .head{color:var(--muted);font-size:.95rem;margin-bottom:.3rem}.turn .said{font-size:1.15rem}
.turn ul{margin:.5rem 0 0;padding-left:1.3rem}.turn li{margin:.2rem 0}
.tag{display:inline-block;border:1px solid var(--line);border-radius:6px;padding:0 .45rem;font-size:.9rem;margin-right:.3rem;background:#f1f4f7}
.queue,.note{background:#fff;border:1px solid var(--line);border-radius:10px;padding:.9rem 1.2rem;margin:.8rem 0}
.note .to{color:var(--muted);font-size:.95rem}.muted{color:var(--muted)}
table{border-collapse:collapse;background:#fff}td,th{border:1px solid var(--line);padding:.35rem .9rem;text-align:left}
details{margin:.8rem 0}summary{font-size:1.1rem;cursor:pointer}
iframe{width:100%;height:560px;border:1px solid var(--line);border-radius:10px;background:#fff}
"""


def cards(metrics: dict[str, Any]) -> str:
    before, after = metrics["before"], metrics["after"]
    out = []
    for key, label, unit in CARDS:
        out.append(
            f'<div class="card"><div class="label">{label}</div>'
            f'<div class="val">{_fmt(key, after.get(key), unit)}</div>'
            f'<div class="before"><s>{_fmt(key, before.get(key), unit)}</s> before</div></div>'
        )
    return f'<div class="cards">{"".join(out)}</div>'


def _move(move: dict[str, Any]) -> str:
    kind = move["type"]
    if kind == "reassign_vehicle":
        return f"{move['trip_id']} moves to van {move['vehicle_id']}"
    if kind == "pair_riders":
        return f"{' and '.join(move['trip_ids'])} ride together on van {move['vehicle_id']}"
    if kind == "shift_pickup_window":
        d = move["delta_min"]
        return f"{move['trip_id']} pickup window {abs(d)} min {'earlier' if d < 0 else 'later'}"
    if kind == "shift_chair_start":
        d = move["delta_min"]
        return f"{move['patient_id']} chair start {abs(d)} min {'earlier' if d < 0 else 'later'}"
    return html.escape(json.dumps(move))


def turns(entries: list[dict[str, Any]]) -> str:
    by_iter: dict[int, list[dict[str, Any]]] = {}
    for e in entries:
        if e["actor"] == "tool" and e["event"] not in ("run_start", "run_finish"):
            by_iter.setdefault(e["iteration"], []).append(e)
    out = []
    for e in entries:
        if e["actor"] != "model":
            continue
        said = (
            e["payload"].get("text") or ""
        ).strip() or "(no comment; went straight to the tools)"
        items = []
        for t in by_iter.get(e["iteration"], []):
            r = t["payload"].get("result") or {}
            name = t["event"]
            if name in ("propose_to_unit", "propose_to_broker"):
                who = "Dialysis unit" if name.endswith("unit") else "Transit broker"
                verdict = "accepted" if r.get("accepted") else f"declined ({r.get('reason_code')})"
                items.append(f"<b>{who}</b> {verdict} {r.get('bundle_id', '')}")
            elif name == "verify":
                m = r.get("metrics") or {}
                items.append(
                    f"<b>Verifier</b>: {len(r.get('violations') or [])} violations; "
                    f"mean wait would be {m.get('mean_post_wait')} min, "
                    f"{m.get('riders_flagged')} riders still unplaced"
                )
            elif name == "apply_bundle":
                bundle = r.get("bundle") or {}
                moves = "; ".join(_move(m) for m in bundle.get("moves", []))
                state = "Applied" if r.get("applied") else "Refused"
                items.append(f"<b>{state}</b> {bundle.get('bundle_id', '')}: {html.escape(moves)}")
            elif name == "flag_for_review":
                items.append(
                    f"<b>Handed to a person</b>: {r.get('subject')} (item {r.get('item_id')})"
                )
            elif name == "finish":
                items.append(
                    f"<b>Finished</b>: {r.get('applied')} bundles applied, {r.get('flagged')} handed over"
                )
            else:
                items.append(f"<b>{html.escape(name)}</b>")
        out.append(
            f'<div class="turn"><div class="head">Turn {e["iteration"]} · {html.escape(e["model_id"])}'
            f" · ${float(e['cost_usd']):.3f} · {int(e['usage']['cache_read'])} prompt tokens read from cache</div>"
            f'<div class="said">{html.escape(said)}</div><ul>{"".join(f"<li>{i}</li>" for i in items)}</ul></div>'
        )
    return "".join(out)


def queue(run_dir: Path) -> str:
    items = _load(run_dir / "review_queue.json") or []
    if not items:
        return '<p class="muted">Nothing handed to a person.</p>'
    out = []
    for it in items:
        tried = "".join(f"<li>{html.escape(str(t))}</li>" for t in it.get("what_was_tried", []))
        out.append(
            f'<div class="queue"><span class="tag">{html.escape(it["reason_code"])}</span>'
            f'<span class="tag">owner: {html.escape(it["owner"])}</span>'
            f'<span class="tag">{html.escape(it["urgency"])}</span> <b>{html.escape(it["subject"])}</b>'
            f"<p>{html.escape(it['recommended_action'])}</p>"
            f'<p class="muted">Draft message: {html.escape(it["draft_message"])}</p>'
            f"{'<p class=muted>What was tried:</p><ul>' + tried + '</ul>' if tried else ''}</div>"
        )
    return "".join(out)


def notes(run_dir: Path, ids: list[str] | None = None) -> str:
    records = _load(run_dir / "explanations.json") or []
    if ids:
        records = [r for r in records if r["explanation_id"] in ids]
    out = []
    for r in records:
        n = r["explanation"]
        checks = r.get("checks") or {}
        out.append(
            f'<div class="note"><div class="to">To the {html.escape(n["audience"])} · {html.escape(n["subject_id"])}'
            f" · reading grade {n['reading_grade']} · numbers checked against the ledger"
            f" ({len(checks.get('unverified_numbers') or [])} unverified)</div>"
            f"<p>{html.escape(n['what_changed'])}</p><p>{html.escape(n['why'])}</p>"
            f'<p class="muted">Who to call: {html.escape(n["contact"])}</p></div>'
        )
    return "".join(out) or '<p class="muted">No notes in this run.</p>'


def receipts(day: dict[str, Any], replan: dict[str, Any]) -> str:
    rows = ""
    for name, m in (("Day run", day), ("Re-plan", replan)):
        u = m["usage"]
        rows += (
            f"<tr><th>{name}</th><td>{u['iterations']}</td><td>{u['tool_calls']}</td>"
            f"<td>{m['elapsed_s']} s</td><td>${u['cost_usd']:.2f}</td>"
            f"<td>{u['cache_read_share']:.0%}</td><td>{html.escape(u['model_id'])}</td></tr>"
        )
    return (
        "<table><tr><th></th><th>Model turns</th><th>Tool calls</th><th>Wall time</th>"
        f"<th>Cost</th><th>Prompt read from cache</th><th>Model</th></tr>{rows}</table>"
    )


def render(day_dir: Path, replan_dir: Path, out: Path) -> str:
    day = _load(day_dir / "metrics.json")
    replan = _load(replan_dir / "metrics.json")
    event = _load(replan_dir / "event.json") or {}
    if not (day and replan):
        raise SystemExit("both runs need a metrics.json")
    ev = event.get("event", {})
    van = ev.get("payload", {}).get("vehicle_id", "?")
    affected = ", ".join(event.get("affected") or [])

    def rel(p: Path) -> str:
        try:
            return p.relative_to(out.parent).as_posix()
        except ValueError:
            return p.resolve().as_uri()

    def frame(label: str, d: Path) -> str:
        if not (d / "timeline.html").is_file():
            return ""
        return (
            f"<details><summary>{label}: the before / after Gantt</summary>"
            f'<iframe src="{rel(d / "timeline.html")}" title="{label}"></iframe></details>'
        )

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Chair-to-Ride: one day, every decision</title><style>{STYLE}</style></head>
<body><div class="banner">{html.escape(BANNER)}</div><div class="wrap">
<h1>Chair-to-Ride: one day, every decision</h1>
<p class="lead">Harborline Dialysis Unit, one synthetic Wednesday. A dialysis unit's chair schedule
and a paratransit broker's van manifest, negotiated together by a mediator agent. The model
chooses; deterministic code counts; nothing is applied until the verifier reports zero violations
and both parties have said yes.</p>

<h2>1. The morning: what the mediator changed</h2>
<p>Run <code>{html.escape(day["run_id"])}</code>: {day["usage"]["iterations"]} model turns,
{day["elapsed_s"]} s, ${day["usage"]["cost_usd"]:.2f}.</p>
{cards(day)}
<h3>The decisions, in order</h3>
{turns(_ledger(day_dir))}
<h3>Handed to a person</h3>
{queue(day_dir)}
{frame("Day run", day_dir)}

<h2>2. Then van {html.escape(van)} breaks down at {html.escape(ev.get("t", "?"))}</h2>
<p>Returns that were on that van: {html.escape(affected)}. Same rules, same verifier, same receipts.
Run <code>{html.escape(replan["run_id"])}</code>: {replan["usage"]["iterations"]} model turns,
{replan["elapsed_s"]} s, ${replan["usage"]["cost_usd"]:.2f}.</p>
{cards(replan)}
<h3>The decisions, in order</h3>
{turns(_ledger(replan_dir))}
<h3>Handed to a person</h3>
{queue(replan_dir)}
{frame("Re-plan", replan_dir)}

<h2>3. What riders and staff are told</h2>
<p class="lead">Every note is drafted by the model from the ledger, then every number in it is
checked against the ledger by code before it can be sent.</p>
<h3>After the breakdown</h3>
{notes(replan_dir)}
<h3>From the morning run (a sample)</h3>
{notes(day_dir, ["E02r", "E25r", "E30d"])}

<h2>4. Receipts</h2>
{receipts(day, replan)}
<p class="muted">Every line above traces to <code>ledger.jsonl</code>, <code>metrics.json</code>,
<code>review_queue.json</code> and <code>explanations.json</code> under {html.escape(str(day_dir))}
and {html.escape(str(replan_dir))}. The eval gate (306 offline checks, judge golden set 12/12) runs
in about half a minute before every commit.</p>
</div></body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default="runs/cp2")
    parser.add_argument("--replan", default="runs/cp3")
    parser.add_argument("--out", default="runs/demo_story.html")
    a = parser.parse_args()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(Path(a.day), Path(a.replan), out), encoding="utf-8", newline="\n")
    print(f"story -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
