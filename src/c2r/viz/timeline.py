"""Before/after Gantt of one run as a single self-contained HTML file: no scripts, no assets.

Meaning is never carried by colour alone: every bar has a pattern and a text label, and every
wait is written in minutes. Contrast is kept at WCAG 2.2 AA with dark text on light fills.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

from c2r.banner import BANNER
from c2r.models import Leg, Manifest, Roster, StopKind
from c2r.state import actual_ready
from c2r.timeutil import to_hhmm, to_min

DAY_START, DAY_END = 5 * 60, 22 * 60
LEFT, ROW, TOP = 64, 22, 28
PX_PER_MIN = 1.1
WIDTH = LEFT + int((DAY_END - DAY_START) * PX_PER_MIN) + 16
CSS = """
body{font:14px/1.4 system-ui,sans-serif;color:#1a1a1a;background:#fff;margin:24px}
h1{font-size:20px}h2{font-size:16px;margin:24px 0 8px}
.banner{background:#fff3cd;color:#5c4400;border:1px solid #b38f00;padding:6px 10px;
display:inline-block;font-weight:600}
table.metrics{border-collapse:collapse;margin:8px 0 12px}
table.metrics th,table.metrics td{border:1px solid #767676;padding:3px 10px;text-align:right}
table.metrics th:first-child,table.metrics td:first-child{text-align:left}
.panel{display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap}
.queue{max-width:360px}.queue li{margin-bottom:6px}
svg text{font:11px system-ui,sans-serif;fill:#1a1a1a}
.legend span{display:inline-block;margin-right:16px}
"""
PATTERNS = """
<defs>
<pattern id="wait" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
<rect width="6" height="6" fill="#fde2e1"/><line x1="0" y1="0" x2="0" y2="6" stroke="#8b1a10" stroke-width="2"/></pattern>
<pattern id="ret" width="6" height="6" patternUnits="userSpaceOnUse">
<rect width="6" height="6" fill="#d9ecff"/><circle cx="3" cy="3" r="1.2" fill="#0b4f8a"/></pattern>
</defs>
"""


def x(minute: int) -> float:
    return LEFT + (minute - DAY_START) * PX_PER_MIN


def _rect(x0: float, x1: float, y: float, fill: str, title: str, h: int = 14) -> str:
    return (
        f'<rect x="{x0:.1f}" y="{y:.1f}" width="{max(x1 - x0, 2):.1f}" height="{h}" '
        f'fill="{fill}" stroke="#333" stroke-width="0.6"><title>{html.escape(title)}</title></rect>'
    )


def _text(x0: float, y: float, text: str, anchor: str = "start") -> str:
    return f'<text x="{x0:.1f}" y="{y:.1f}" text-anchor="{anchor}">{html.escape(text)}</text>'


def gantt(roster: Roster, manifest: Manifest, title: str) -> str:
    riders = {r.rider_id: r for r in roster.riders}
    trips = {t.trip_id: t for t in manifest.trips}
    pickups = {
        s.trip_id: to_min(s.eta)
        for r in manifest.routes
        for s in r.stops
        if s.kind == StopKind.pickup
    }
    dropoffs = {
        s.trip_id: to_min(s.eta)
        for r in manifest.routes
        for s in r.stops
        if s.kind == StopKind.dropoff
    }
    chairs = sorted({p.chair_id for p in roster.patients})
    vehicles = sorted({r.vehicle_id for r in manifest.routes})
    rows = chairs + vehicles
    height = TOP + ROW * len(rows) + 12
    out = [
        f'<svg width="{WIDTH}" height="{height}" role="img" aria-label="{html.escape(title)}">',
        PATTERNS,
    ]
    for hour in range(DAY_START, DAY_END + 1, 60):
        out.append(
            f'<line x1="{x(hour):.1f}" y1="{TOP - 6}" x2="{x(hour):.1f}" y2="{height}" stroke="#ccc"/>'
        )
        out.append(_text(x(hour), TOP - 10, to_hhmm(hour), "middle"))
    for index, row in enumerate(rows):
        y = TOP + index * ROW
        out.append(_text(4, y + 12, row))
        if row in chairs:
            waits: list[str] = []
            for p in sorted(
                (p for p in roster.patients if p.chair_id == row), key=lambda p: p.start_time
            ):
                start = to_min(p.start_time)
                end = start + p.late_start_min + int(p.rx_duration_min) + p.runover_min
                ready = actual_ready(p)
                label = (
                    f"{p.patient_id} on {p.start_time}, off {to_hhmm(end)}, ready {to_hhmm(ready)}"
                )
                out.append(_rect(x(start), x(end), y + 2, "#e6e6e6", label))
                out.append(
                    _rect(
                        x(end),
                        x(ready),
                        y + 2,
                        "#fff",
                        f"{p.patient_id} recovery to {to_hhmm(ready)}",
                    )
                )
                out.append(_text(x(start) + 3, y + 13, p.patient_id))
                trip = trips.get(f"{p.patient_id}f")
                if (
                    trip
                    and trip.trip_id in pickups
                    and riders[trip.rider_id].provider.value == "broker"
                ):
                    wait = pickups[trip.trip_id] - ready
                    if wait > 0:
                        # Drawn after every session bar on the row so nothing paints over them.
                        waits.append(
                            _rect(
                                x(ready),
                                x(pickups[trip.trip_id]),
                                y + 2,
                                "url(#wait)",
                                f"{p.patient_id} waits {wait} min for the van",
                            )
                        )
                        waits.append(_text(x(ready) + 3, y + 13, f"wait {wait}"))
            out.extend(waits)
        else:
            route = next(r for r in manifest.routes if r.vehicle_id == row)
            for stop in route.stops:
                if stop.kind != StopKind.pickup:
                    continue
                trip = trips[stop.trip_id]
                end = dropoffs.get(stop.trip_id, to_min(stop.eta))
                fill = "url(#ret)" if trip.leg == Leg.from_ else "#f2f2f2"
                leg = "home" if trip.leg == Leg.from_ else "to unit"
                label = f"{stop.trip_id} {leg} {stop.eta}-{to_hhmm(end)}"
                out.append(_rect(x(to_min(stop.eta)), x(end), y + 4, fill, label, 10))
                out.append(_text(x(to_min(stop.eta)) + 2, y + 13, stop.trip_id[:3]))
    out.append("</svg>")
    return "\n".join(out)


def metrics_table(before: dict[str, Any], after: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{before[k]:g}</td><td>{after[k]:g}</td></tr>"
        for k in before
    )
    return f'<table class="metrics"><tr><th>metric</th><th>before</th><th>after</th></tr>{rows}</table>'


def queue_panel(items: list[dict[str, Any]]) -> str:
    if not items:
        return "<p>Review queue: empty.</p>"
    lis = "".join(
        f"<li><strong>{html.escape(i['item_id'])} {html.escape(i['subject'])}</strong> "
        f"[{html.escape(i['reason_code'])}] {html.escape(i['recommended_action'])} "
        f"(owner: {html.escape(i['owner'])}, {html.escape(i['urgency'])})</li>"
        for i in items
    )
    return f'<div class="queue"><h2>Review queue ({len(items)})</h2><ol>{lis}</ol></div>'


def render(run_dir: Path) -> str:
    schedules = {}
    for name in ("before", "after"):
        raw = json.loads((run_dir / f"schedule_{name}.json").read_text(encoding="utf-8"))
        schedules[name] = (
            Roster.model_validate(raw["roster"]),
            Manifest.model_validate(raw["manifest"]),
        )
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    queue_path = run_dir / "review_queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.is_file() else []
    legend = (
        '<p class="legend"><span>grey bar: on the chair (late start and run-over included), white tail: recovery</span>'
        "<span>red hatched bar + 'wait N': minutes waiting for the van after ready</span>"
        "<span>dotted blue bar: ride home; plain bar: ride to the unit</span></p>"
    )
    panels = "".join(
        f"<h2>{name.title()}: mean post-wait {metrics[name]['mean_post_wait']:g} min, "
        f"p90 {metrics[name]['p90_post_wait']:g} min</h2>{gantt(*schedules[name], name)}"
        for name in ("before", "after")
    )
    event_path = run_dir / "event.json"
    heading = "Chair-to-Ride: before and after"
    if event_path.is_file():  # a perturbation run: "before" is the moment the event hit
        event = json.loads(event_path.read_text(encoding="utf-8"))["event"]
        what = ", ".join(f"{k} {v}" for k, v in sorted(event["payload"].items()))
        heading = f"Chair-to-Ride: {event['type']} at {event['t']} ({what}) and the re-plan"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>Chair-to-Ride timeline: {html.escape(run_dir.name)}</title><style>{CSS}</style></head>"
        f'<body><p class="banner">{html.escape(BANNER)}</p><h1>{html.escape(heading)}</h1>'
        f'<div class="panel"><div>{metrics_table(metrics["before"], metrics["after"])}{legend}{panels}</div>'
        f"{queue_panel(queue)}</div></body></html>"
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    target = run_dir / "timeline.html"
    target.write_text(render(run_dir), encoding="utf-8", newline="\n")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
