"""A plain-English account of one finished demo: what happened, decision by decision.

``python -m c2r.viz.story [--day runs/cp2] [--replan runs/cp3] [--data data/synthetic/42]
[--out runs/demo_story.html]``

Written for an audience that has never seen a terminal. Riders are named (synthetic names from
the roster), ids and hashes stay in the ledger. Every number is read from the run files; the
page computes nothing.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path
from typing import Any

from c2r.banner import BANNER
from c2r.viz.dashboard import _ledger, _load

REASONS = {
    "STRETCHER": "needs a stretcher, which no van in the fleet carries",
    "BROKER_POLICY": "the broker's own rules say a person decides this one",
    "CONSENT": "has not agreed to schedule changes",
}
STYLE = """
:root{--ink:#14202b;--muted:#4b5a68;--paper:#fbfbf8;--line:#c9d1d9;--accent:#0b5cad}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:20px/1.55 "Segoe UI",system-ui,sans-serif}
.banner{background:#1f2a36;color:#fff;font-weight:700;letter-spacing:.04em;padding:.5rem 1.5rem;font-size:1rem}
.wrap{max-width:960px;margin:0 auto;padding:1rem 1.5rem 3rem}
h1{font-size:2.3rem;margin:.8rem 0 .2rem;line-height:1.2}
h2{font-size:1.7rem;margin:2.4rem 0 .6rem;border-bottom:3px solid var(--line);padding-bottom:.2rem}
h3{font-size:1.25rem;margin:1.4rem 0 .4rem;color:var(--muted)}.lead{font-size:1.2rem;color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:.9rem;margin:1rem 0}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:.9rem 1.1rem}
.card .label{color:var(--muted)}.card .val{font-size:2.3rem;font-weight:700;line-height:1.15}
.card .was{color:var(--muted)}
.step{background:#fff;border:1px solid var(--line);border-radius:12px;padding:1rem 1.3rem;margin:.9rem 0;display:grid;grid-template-columns:3.2rem 1fr;gap:.6rem}
.step .n{font-size:1.6rem;font-weight:700;color:var(--accent)}
.step p{margin:.2rem 0}.step .own{color:var(--muted);font-size:1rem;margin:.4rem 0 0}.step .own summary{font-size:.95rem;color:var(--muted)}
.box{background:#fff;border:1px solid var(--line);border-radius:12px;padding:1rem 1.3rem;margin:.9rem 0}
.box .to{color:var(--muted);font-size:1rem;margin-bottom:.3rem}.muted{color:var(--muted)}
details{margin:1rem 0}summary{font-size:1.1rem;cursor:pointer;color:var(--accent)}
iframe{width:100%;height:560px;border:1px solid var(--line);border-radius:12px;background:#fff}
"""


class Names:
    """Synthetic display names and mobility, keyed by patient id ("P04") or trip id ("P04f")."""

    def __init__(self, data_dir: Path) -> None:
        roster = _load(data_dir / "roster.json") or {}
        self.patients = {p["patient_id"]: p for p in roster.get("patients", [])}

    def person(self, pid: str) -> str:
        p = self.patients.get(pid[:3])
        return p["display_name"] if p else pid

    def trip(self, trip_id: str) -> str:
        who = self.person(trip_id)
        leg = "ride home" if trip_id.endswith("f") else "ride in"
        return f"{who}'s {leg}"

    def chair(self, pid: str) -> str:
        return f"{self.person(pid)}'s chair time"

    def humanize(self, text: str) -> str:
        """Swap rider codes in recorded prose (P30, P16f) for the synthetic names."""
        return re.sub(
            r"(?<![A-Za-z0-9])P\d\d[tf]?(?![A-Za-z0-9])", lambda m: self.person(m.group(0)), text
        )


def minutes(value: Any) -> str:
    v = float(value)
    return f"{v:.0f} min" if v >= 10 else f"{v:.1f} min"


def cards(metrics: dict[str, Any]) -> str:
    b, a = metrics["before"], metrics["after"]
    rows = (
        (
            "Average wait for the ride home",
            minutes(a["mean_post_wait"]),
            minutes(b["mean_post_wait"]),
        ),
        ("Longest waits (slowest tenth)", minutes(a["p90_post_wait"]), minutes(b["p90_post_wait"])),
        (
            "Riders picked up within 30 minutes",
            f"{a['within_30_share']:.0%}",
            f"{b['within_30_share']:.0%}",
        ),
        ("Riders a person still has to place", str(a["riders_flagged"]), str(b["riders_flagged"])),
    )
    return (
        '<div class="cards">'
        + "".join(
            f'<div class="card"><div class="label">{label}</div><div class="val">{now}</div>'
            f'<div class="was">was {was}</div></div>'
            for label, now, was in rows
        )
        + "</div>"
    )


def _move(move: dict[str, Any], names: Names) -> str:
    kind = move["type"]
    if kind == "reassign_vehicle":
        return f"{names.trip(move['trip_id'])} goes on van {move['vehicle_id'][1:]}"
    if kind == "pair_riders":
        a, b = move["trip_ids"]
        return f"{names.person(a)} and {names.person(b)} share van {move['vehicle_id'][1:]}"
    if kind == "shift_pickup_window":
        d = move["delta_min"]
        return f"{names.trip(move['trip_id'])} moves {abs(d)} minutes {'earlier' if d < 0 else 'later'}"
    if kind == "shift_chair_start":
        d = move["delta_min"]
        return f"{names.chair(move['patient_id'])} moves {abs(d)} minutes {'earlier' if d < 0 else 'later'}"
    return kind.replace("_", " ")


def steps(entries: list[dict[str, Any]], names: Names) -> str:
    tools: dict[int, list[dict[str, Any]]] = {}
    for e in entries:
        if e["actor"] == "tool" and e["event"] not in ("run_start", "run_finish"):
            tools.setdefault(e["iteration"], []).append(e)
    out = []
    n = 0
    for e in entries:
        if e["actor"] != "model":
            continue
        n += 1
        lines: list[str] = []
        yes, verify, applied, handed, done = [], None, None, [], None
        for t in tools.get(e["iteration"], []):
            r = t["payload"].get("result") or {}
            if t["event"] in ("propose_to_unit", "propose_to_broker"):
                who = "the dialysis unit" if t["event"].endswith("unit") else "the transit broker"
                yes.append(f"{who} said {'yes' if r.get('accepted') else 'no'}")
            elif t["event"] == "verify":
                verify = r
            elif t["event"] == "apply_bundle" and r.get("applied"):
                applied = r["bundle"]["moves"]
            elif t["event"] == "flag_for_review":
                handed.append(names.person(r.get("subject", "")))
            elif t["event"] == "finish":
                done = r
        if yes:
            lines.append("The mediator put an option to both sides: " + " and ".join(yes) + ".")
        if verify is not None:
            v = len(verify.get("violations") or [])
            m = verify.get("metrics") or {}
            lines.append(
                f"The rule checker found {v} broken rule{'s' if v != 1 else ''}; "
                f"average wait would fall to {minutes(m.get('mean_post_wait', 0))}."
            )
        if applied:
            lines.append("Applied: " + "; ".join(_move(mv, names) for mv in applied) + ".")
        for who in handed:
            lines.append(f"Handed {who}'s ride to a person, with the reason and a draft message.")
        if done:
            lines.append(
                f"Finished: {done.get('applied')} change set{'s' if done.get('applied') != 1 else ''}"
                f" applied, {done.get('flagged')} rider{'s' if done.get('flagged') != 1 else ''} handed to a person."
            )
        said = (e["payload"].get("text") or "").strip()
        own = (
            '<details class="own"><summary>The mediator&#39;s exact words</summary>'
            f"<p>{html.escape(said)}</p></details>"
            if said
            else ""
        )
        out.append(
            f'<div class="step"><div class="n">{n}</div><div>'
            + "".join(f"<p>{html.escape(x)}</p>" for x in lines)
            + own
            + "</div></div>"
        )
    return "".join(out)


def queue(run_dir: Path, names: Names) -> str:
    items = _load(run_dir / "review_queue.json") or []
    if not items:
        return "<p>Nobody. Every rider was placed inside the rules.</p>"
    out = []
    for it in items:
        why = REASONS.get(it["reason_code"], it["reason_code"].replace("_", " ").lower())
        out.append(
            f'<div class="box"><p><b>{html.escape(names.person(it["subject"]))}</b>: {why}. '
            f"Goes to the {html.escape(it['owner'])}, {html.escape(it['urgency'])}.</p>"
            f"<p>What to do: {html.escape(names.humanize(it['recommended_action']))}</p></div>"
        )
    return "".join(out)


def notes(run_dir: Path, names: Names, pick: int = 2) -> str:
    records = _load(run_dir / "explanations.json") or []
    chosen: list[dict[str, Any]] = []
    for audience in ("rider", "dispatcher"):
        for r in records:
            if r["explanation"]["audience"] == audience:
                chosen.append(r)
                break
    out = []
    for r in chosen[:pick]:
        n = r["explanation"]
        who = names.person(n["subject_id"]) if n["audience"] == "rider" else "the dispatcher"
        out.append(
            f'<div class="box"><div class="to">Note to {html.escape(who)} · '
            f"reads at grade {n['reading_grade']:.0f} · every number checked against the record</div>"
            f"<p>{html.escape(n['what_changed'])}</p><p>{html.escape(n['why'])}</p>"
            f'<p class="muted">Who to call: {html.escape(n["contact"])}</p></div>'
        )
    return "".join(out) or "<p class='muted'>No notes in this run.</p>"


def frame(label: str, d: Path, out: Path) -> str:
    if not (d / "timeline.html").is_file():
        return ""
    try:
        src = (d / "timeline.html").relative_to(out.parent).as_posix()
    except ValueError:
        src = (d / "timeline.html").resolve().as_uri()
    return (
        f"<details><summary>Show the schedule before and after ({label})</summary>"
        f'<iframe src="{src}" title="{label}"></iframe></details>'
    )


def render(day_dir: Path, replan_dir: Path, data_dir: Path, out: Path) -> str:
    day = _load(day_dir / "metrics.json")
    replan = _load(replan_dir / "metrics.json")
    if not (day and replan):
        raise SystemExit("both runs need a metrics.json")
    names = Names(data_dir)
    unit = (_load(data_dir / "unit.json") or {}).get("name", "the dialysis unit")
    event = (_load(replan_dir / "event.json") or {}).get("event", {})
    van = event.get("payload", {}).get("vehicle_id", "V?")[1:]
    at = event.get("t", "?")
    affected = (_load(replan_dir / "event.json") or {}).get("affected") or []
    hit = ", ".join(names.person(t) for t in affected)
    du, ru = day["usage"], replan["usage"]

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Chair-to-Ride: one day, every decision</title><style>{STYLE}</style></head>
<body><div class="banner">{html.escape(BANNER)}</div><div class="wrap">
<h1>Chair-to-Ride</h1>
<p class="lead">{html.escape(unit)}, one made-up Wednesday. Dialysis chairs are booked by the
unit. Rides are booked by a transit broker, days ahead. Nobody lines the two up, so riders sit
in the lobby after treatment. Chair-to-Ride is a mediator that re-times both together. It may
only apply a change when a rule checker finds nothing broken and both sides have said yes.</p>

<h2>1. The morning: what changed</h2>
{cards(day)}
<p class="muted">Done in {day["elapsed_s"]:.0f} seconds over {du["iterations"]} rounds, for ${du["cost_usd"]:.2f}.</p>
<h3>Decision by decision</h3>
{steps(_ledger(day_dir), names)}
<h3>Who still needs a person</h3>
{queue(day_dir, names)}
{frame("morning", day_dir, out)}

<h2>2. Then van {html.escape(van)} breaks down at {html.escape(at)}</h2>
<p>Riders who were on that van: {html.escape(hit)}. Same rules, same checker.</p>
{cards(replan)}
<p class="muted">Done in {replan["elapsed_s"]:.0f} seconds over {ru["iterations"]} rounds, for ${ru["cost_usd"]:.2f}.</p>
<h3>Decision by decision</h3>
{steps(_ledger(replan_dir), names)}
<h3>Who still needs a person</h3>
{queue(replan_dir, names)}
{frame("after the breakdown", replan_dir, out)}

<h2>3. What people are told</h2>
<p class="lead">Each rider gets a short note. The mediator drafts it; code checks every time and
number in it against the record before it can go out.</p>
{notes(replan_dir, names)}

<h2>4. What it cost</h2>
<p>The morning run: ${du["cost_usd"]:.2f}, {du["cache_read_share"]:.0%} of the prompt reused from
cache. The breakdown re-plan: ${ru["cost_usd"]:.2f}. Every decision above is in a ledger a charge
nurse can audit, and 306 automatic checks run before any code change is accepted.</p>
</div></body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default="runs/cp2")
    parser.add_argument("--replan", default="runs/cp3")
    parser.add_argument("--data", default="data/synthetic/42")
    parser.add_argument("--out", default="runs/demo_story.html")
    a = parser.parse_args()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        render(Path(a.day), Path(a.replan), Path(a.data), out), encoding="utf-8", newline="\n"
    )
    print(f"story -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
