"""Synthetic day generator: numpy makes every number, Sonnet 5 only the narrative fields."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from itertools import permutations
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel
from referencing import Registry, Resource

from c2r.models import (
    Chair,
    Event,
    EventType,
    Fleet,
    Leg,
    Load,
    Manifest,
    Mobility,
    Node,
    Patient,
    Provider,
    Rider,
    Roster,
    Route,
    RouteStop,
    Shift,
    StopKind,
    Travel,
    Trip,
    TripStatus,
    Unit,
    Vehicle,
    Window,
)
from c2r.timeutil import to_hhmm, to_min, window_min

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = "c2r.synth v1"
LLM_GENERATOR = "c2r.synth v1+llm"
NOTE_MODEL = "claude-sonnet-5"
UNIT_NAME = "Harborline Dialysis Unit"
UNIT_ID = "U1"
UNIT_NODE = 0
DEPOT_NODE = 1
NODE_COUNT = 40
GRID_SPAN = 10.0
ZONES = ["A", "B", "C", "D"]
CHAIR_COUNT = 12
SHIFT_IDS = ["S1", "S2", "S3"]
RX_COUNTS = {210: 5, 225: 7, 240: 16, 255: 4, 270: 4}
MOBILITY_COUNTS = {"ambulatory": 20, "assist": 5, "wheelchair": 10, "stretcher": 1}
HYPOTENSION_COUNT = 7
FIXED_PER_SHIFT = 2
NON_CONSENT_PER_SHIFT = 3
RIDER_COUNT = 22
FAMILY_COUNT = 4
CAREGIVER_COUNT = 6
LANGUAGE_COUNTS = {"en": 17, "es": 3, "zh": 2}
TO_LEG_LEAD_MIN = 20
TO_LEG_WINDOW_MIN = 30
TO_LEG_ARRIVALS = (10, 15, 20, 25, 30, 5)
MIN_TRAVEL_MIN = 6
MAX_TRAVEL_MIN = 38
FIXED_REASONS = [
    "vascular access schedule",
    "post-session cardiac monitoring",
    "nephrologist order for a fixed start",
]
MOBILITY_NURSE = {
    "ambulatory": "Walks on unaided.",
    "assist": "Needs a hand to transfer.",
    "wheelchair": "Wheelchair.",
    "stretcher": "Stretcher transfer, two crew.",
}
MOBILITY_RIDER = {
    "ambulatory": "Walks to the van unaided.",
    "assist": "Needs a hand at the curb.",
    "wheelchair": "Wheelchair lift required.",
    "stretcher": "Stretcher transport, two crew.",
}
LANGUAGE_RIDER = {"en": "", "es": "Prefers Spanish.", "zh": "Prefers Mandarin."}
ADD_ON_MOBILITY = ["ambulatory", "assist", "wheelchair"]
CLASS_OF = {
    "ambulatory": "ambulatory",
    "assist": "ambulatory",
    "wheelchair": "wheelchair",
    "stretcher": "stretcher",
}
NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "display_name": {"type": "string"},
        "nurse_note": {"type": "string"},
        "rider_note": {"type": "string"},
    },
    "required": ["display_name", "nurse_note", "rider_note"],
    "additionalProperties": False,
}


@dataclass
class _Slot:
    shift_id: str
    chair_id: str
    start: int
    cap: int


@dataclass
class _Job:
    trip: Trip
    mobility: str
    home_node: int
    shift_id: str
    chair_start: int
    ready: int
    service: int
    requeued: bool = False


@dataclass
class _Task:
    start: int
    end: int
    start_node: int
    end_node: int
    stops: list[RouteStop]


@dataclass
class _Van:
    vehicle: Vehicle
    tasks: list[_Task] = field(default_factory=list)


def _rules() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))


def _registry() -> Registry:
    registry = Registry()
    for path in sorted((ROOT / "specs" / "schemas").glob("*.schema.json")):
        contents = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(contents["$id"], Resource.from_contents(contents))
    return registry


def _validator(registry: Registry, name: str) -> Draft202012Validator:
    schema = json.loads((ROOT / "specs" / "schemas" / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=registry)


def _write(path: Path, model: BaseModel, validator: Draft202012Validator) -> None:
    payload = model.model_dump(mode="json")
    validator.validate(payload)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def _slots(rng: np.random.Generator, rules: dict[str, Any]) -> list[_Slot]:
    unit = rules["unit"]
    order = [int(c) for c in rng.permutation(CHAIR_COUNT)]
    bins = {f"C{order[i] + 1:02d}": i // unit["stagger_cohort_size"] for i in range(CHAIR_COUNT)}
    starts = {
        shift: {
            chair: to_min(unit["shifts"][shift][0]) + bins[chair] * unit["stagger_step_min"]
            for chair in bins
        }
        for shift in SHIFT_IDS
    }
    slots: list[_Slot] = []
    for index, shift in enumerate(SHIFT_IDS):
        for number in range(1, CHAIR_COUNT + 1):
            chair = f"C{number:02d}"
            start = starts[shift][chair]
            if index + 1 < len(SHIFT_IDS):
                limit = starts[SHIFT_IDS[index + 1]][chair] - unit["turnover_min"]
            else:
                limit = to_min(unit["close_time"])
            slots.append(_Slot(shift, chair, start, limit - start))
    return slots


def _durations(rng: np.random.Generator, slots: list[_Slot]) -> list[int]:
    pool = sorted([d for d, count in RX_COUNTS.items() for _ in range(count)], reverse=True)
    free = list(range(len(slots)))
    out = [0] * len(slots)
    for duration in pool:
        choices = [index for index in free if slots[index].cap >= duration]
        index = choices[int(rng.integers(len(choices)))]
        free.remove(index)
        out[index] = duration
    return out


def _shuffled(rng: np.random.Generator, items: list[str]) -> list[str]:
    return [items[int(i)] for i in rng.permutation(len(items))]


def _unit(seed: int, rules: dict[str, Any]) -> Unit:
    unit = rules["unit"]
    chairs = [
        Chair(
            chair_id=f"C{number:02d}",
            station_type="isolation" if number == CHAIR_COUNT else "standard",
            available_windows=[Window(root=[unit["shifts"]["S1"][0], unit["close_time"]])],
        )
        for number in range(1, CHAIR_COUNT + 1)
    ]
    shifts = [
        Shift(
            shift_id=shift,
            putton_start=unit["shifts"][shift][0],
            putton_end=unit["shifts"][shift][1],
        )
        for shift in SHIFT_IDS
    ]
    return Unit(
        synthetic=True,
        generator=GENERATOR,
        seed=seed,
        unit_id=UNIT_ID,
        name=UNIT_NAME,
        chairs=chairs,
        shifts=shifts,
        stagger_cohort_size=unit["stagger_cohort_size"],
        stagger_step_min=unit["stagger_step_min"],
        turnover_min=unit["turnover_min"],
        close_time=unit["close_time"],
        policy_text=(ROOT / "config" / "unit_policy.md").read_text(encoding="utf-8"),
    )


def _travel(rng: np.random.Generator, seed: int) -> Travel:
    nodes: list[Node] = []
    points: list[tuple[float, float]] = []
    for node_id in range(NODE_COUNT):
        zone = ZONES[node_id % len(ZONES)]
        if node_id == UNIT_NODE:
            x, y = GRID_SPAN, GRID_SPAN
        elif node_id == DEPOT_NODE:
            x, y = GRID_SPAN + 0.5, GRID_SPAN - 0.5
        else:
            x = round(float(rng.uniform(0.0, GRID_SPAN)) + (GRID_SPAN if zone in "BD" else 0.0), 2)
            y = round(float(rng.uniform(0.0, GRID_SPAN)) + (GRID_SPAN if zone in "CD" else 0.0), 2)
        points.append((x, y))
        nodes.append(Node(node_id=node_id, zone=zone, x=x, y=y))
    matrix = [[0] * NODE_COUNT for _ in range(NODE_COUNT)]
    for i in range(NODE_COUNT):
        for j in range(i + 1, NODE_COUNT):
            manhattan = abs(points[i][0] - points[j][0]) + abs(points[i][1] - points[j][1])
            noisy = round(manhattan + float(rng.normal(0.0, 1.5)))
            minutes = int(min(max(noisy, MIN_TRAVEL_MIN), MAX_TRAVEL_MIN))
            matrix[i][j] = minutes
            matrix[j][i] = minutes
    return Travel(synthetic=True, generator=GENERATOR, seed=seed, nodes=nodes, matrix=matrix)


def _fleet(seed: int, rules: dict[str, Any]) -> Fleet:
    shift = Window(root=list(rules["broker"]["vehicle_shift"]))
    capacity = rules["broker"]["van_capacity"]
    vehicles = [
        Vehicle(
            vehicle_id=f"V{number}",
            cap_ambulatory=capacity["standard" if number <= 3 else "lift"]["ambulatory"],
            cap_wheelchair=capacity["standard" if number <= 3 else "lift"]["wheelchair"],
            cap_stretcher=capacity["standard" if number <= 3 else "lift"]["stretcher"],
            shift=shift,
            depot_node=DEPOT_NODE,
            status="ok",
        )
        for number in range(1, 6)
    ]
    return Fleet(synthetic=True, generator=GENERATOR, seed=seed, vehicles=vehicles)


def _nurse_note(patient: Patient) -> str:
    parts = [
        (
            f"{patient.shift_id.value} start {patient.start_time}, "
            f"chair {patient.chair_id}, {int(patient.rx_duration_min)} min."
        ),
        MOBILITY_NURSE[patient.mobility.value],
    ]
    if int(patient.recovery_buffer_min) == 35:
        parts.append("Hypotension on previous sessions; extended recovery buffer.")
    if patient.clinically_fixed:
        parts.append(f"Start time clinically fixed: {patient.fixed_reason}.")
    if not patient.consent_to_move:
        parts.append("Has not consented to schedule changes.")
    return " ".join(parts)


def _rider_note(
    mobility: str, node: int, zone: str, language: str, caregiver: Window | None
) -> str:
    parts = [f"Pickup from Node {node}, Zone {zone}.", MOBILITY_RIDER[mobility]]
    if caregiver is not None:
        opens, closes = caregiver.root
        parts.append(f"Caregiver available {opens} to {closes}.")
    if LANGUAGE_RIDER[language]:
        parts.append(LANGUAGE_RIDER[language])
    return " ".join(parts)


def _patients(
    rng: np.random.Generator, rules: dict[str, Any], slots: list[_Slot], names: list[str]
) -> list[Patient]:
    synth = rules["synth"]
    durations = _durations(rng, slots)
    mobilities = _shuffled(rng, [m for m, n in MOBILITY_COUNTS.items() for _ in range(n)])
    fixed: set[int] = set()
    non_consent: set[int] = set()
    for index in range(len(SHIFT_IDS)):
        base = index * CHAIR_COUNT
        fixed |= {base + int(i) for i in rng.choice(CHAIR_COUNT, FIXED_PER_SHIFT, replace=False)}
        non_consent |= {
            base + int(i) for i in rng.choice(CHAIR_COUNT, NON_CONSENT_PER_SHIFT, replace=False)
        }
    hypotension = {int(i) for i in rng.choice(len(slots), HYPOTENSION_COUNT, replace=False)}
    late = {
        int(i): int(rng.integers(synth["late_start_min"], synth["late_start_max"] + 1))
        for i in sorted(
            rng.choice(len(slots), round(synth["late_start_share"] * len(slots)), replace=False)
        )
    }
    runover = {
        int(i): int(rng.integers(0, synth["runover_max_min"] + 1))
        for i in sorted(
            rng.choice(len(slots), round(synth["runover_share"] * len(slots)), replace=False)
        )
    }
    reasons = [FIXED_REASONS[int(i)] for i in rng.integers(0, len(FIXED_REASONS), len(slots))]
    patients: list[Patient] = []
    for index, slot in enumerate(slots):
        patient = Patient(
            patient_id=f"P{index + 1:02d}",
            display_name=names[index],
            rx_days="MWF",
            rx_duration_min=durations[index],
            shift_id=slot.shift_id,
            chair_id=slot.chair_id,
            start_time=to_hhmm(slot.start),
            clinically_fixed=index in fixed,
            fixed_reason=reasons[index] if index in fixed else None,
            consent_to_move=index not in non_consent,
            mobility=mobilities[index],
            recovery_buffer_min=(
                rules["recovery_buffer_min"]["hypotension"]
                if index in hypotension
                else rules["recovery_buffer_min"]["default"]
            ),
            nurse_note="",
            moves_this_week=0,
            rider_id=None,
            late_start_min=late.get(index, 0),
            runover_min=runover.get(index, 0),
        )
        patient.nurse_note = _nurse_note(patient)
        patients.append(patient)
    return patients


def _riders(rng: np.random.Generator, patients: list[Patient], nodes: list[Node]) -> list[Rider]:
    stretcher = next(i for i, p in enumerate(patients) if p.mobility == Mobility.stretcher)
    others = [i for i in range(len(patients)) if i != stretcher]
    chosen = sorted(
        [stretcher] + [int(i) for i in rng.choice(others, RIDER_COUNT - 1, replace=False)]
    )
    family = {
        int(i)
        for i in rng.choice([i for i in chosen if i != stretcher], FAMILY_COUNT, replace=False)
    }
    homes = [int(n) for n in rng.choice(range(2, NODE_COUNT), RIDER_COUNT, replace=False)]
    languages = _shuffled(rng, [c for c, n in LANGUAGE_COUNTS.items() for _ in range(n)])
    caregivers = {int(i) for i in rng.choice(RIDER_COUNT, CAREGIVER_COUNT, replace=False)}
    opens = [int(h) for h in rng.integers(12, 16, RIDER_COUNT)]
    riders: list[Rider] = []
    for slot, index in enumerate(chosen):
        rider_id = f"R{slot + 1:02d}"
        patients[index].rider_id = rider_id
        window = Window(root=[to_hhmm(opens[slot] * 60), "20:00"]) if slot in caregivers else None
        riders.append(
            Rider(
                rider_id=rider_id,
                patient_id=patients[index].patient_id,
                home_node=homes[slot],
                language=languages[slot],
                caregiver_window=window,
                rider_note=_rider_note(
                    patients[index].mobility.value,
                    homes[slot],
                    nodes[homes[slot]].zone.value,
                    languages[slot],
                    window,
                ),
                provider=Provider.family if index in family else Provider.broker,
            )
        )
    return riders


def _jobs(
    rng: np.random.Generator,
    rules: dict[str, Any],
    patients: list[Patient],
    riders: list[Rider],
) -> tuple[list[Trip], list[_Job]]:
    synth = rules["synth"]
    width = rules["broker"]["pickup_window_min"]
    by_id = {patient.patient_id: patient for patient in patients}
    broker = [rider for rider in riders if rider.provider == Provider.broker]
    eligible = [r.rider_id for r in broker if by_id[r.patient_id].mobility != Mobility.stretcher]
    will_call = {str(r) for r in rng.choice(eligible, synth["will_call_count"], replace=False)}
    trips: list[Trip] = []
    jobs: list[_Job] = []
    for rider in broker:
        patient = by_id[rider.patient_id]
        start = to_min(patient.start_time)
        scheduled_ready = start + int(patient.rx_duration_min) + int(patient.recovery_buffer_min)
        ready = scheduled_ready + patient.late_start_min + patient.runover_min
        stretcher = patient.mobility == Mobility.stretcher
        called = rider.rider_id in will_call
        opens = scheduled_ready + synth["standing_order_offset_min"]
        service = ready + synth["will_call_delay_min"] if called else opens
        legs = [
            Trip(
                trip_id=f"{patient.patient_id}t",
                rider_id=rider.rider_id,
                leg=Leg.to,
                origin_node=rider.home_node,
                dest_node=UNIT_NODE,
                requested_time=to_hhmm(start - TO_LEG_LEAD_MIN),
                window=Window(root=[to_hhmm(start - TO_LEG_WINDOW_MIN), to_hhmm(start)]),
                vehicle_id=None,
                seq=None,
                status=TripStatus.queued if stretcher else TripStatus.scheduled,
            ),
            Trip(
                trip_id=f"{patient.patient_id}f",
                rider_id=rider.rider_id,
                leg=Leg.from_,
                origin_node=UNIT_NODE,
                dest_node=rider.home_node,
                requested_time=to_hhmm(service if called else opens + width // 2),
                window=None if called else Window(root=[to_hhmm(opens), to_hhmm(opens + width)]),
                vehicle_id=None,
                seq=None,
                status=TripStatus.queued
                if stretcher
                else (TripStatus.will_call if called else TripStatus.scheduled),
            ),
        ]
        trips.extend(legs)
        if stretcher:
            continue
        for trip in legs:
            jobs.append(
                _Job(
                    trip=trip,
                    mobility=patient.mobility.value,
                    home_node=rider.home_node,
                    shift_id=patient.shift_id.value,
                    chair_start=start,
                    ready=ready,
                    service=to_min(trip.requested_time) if trip.leg == Leg.to else service,
                )
            )
    return trips, jobs


def _capacity(vehicle: Vehicle) -> dict[str, int]:
    return {
        "ambulatory": vehicle.cap_ambulatory,
        "wheelchair": vehicle.cap_wheelchair,
        "stretcher": vehicle.cap_stretcher,
    }


def _openings(van: _Van, shift: tuple[int, int]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    heads = [(shift[0], van.vehicle.depot_node)] + [(t.end, t.end_node) for t in van.tasks]
    tails = [(t.start, t.start_node) for t in van.tasks] + [(shift[1], -1)]
    return list(zip(heads, tails, strict=True))


def _commit(van: _Van, task: _Task) -> None:
    van.tasks.append(task)
    van.tasks.sort(key=lambda item: item.start)


def _place_to(
    vans: list[_Van],
    job: _Job,
    matrix: list[list[int]],
    dwell: dict[str, int],
    shift: tuple[int, int],
    floor: int,
) -> bool:
    klass = CLASS_OF[job.mobility]
    empty = Load(ambulatory=0, wheelchair=0, stretcher=0)
    aboard = Load(**{**empty.model_dump(), klass: 1})
    for early in TO_LEG_ARRIVALS:
        arrive = job.chair_start - early
        board = arrive - dwell[job.mobility] - matrix[job.home_node][UNIT_NODE]
        finish = arrive + dwell[job.mobility]
        if board < floor or finish > shift[1]:
            continue
        for van in sorted(vans, key=lambda v: (len(v.tasks), v.vehicle.vehicle_id)):
            if _capacity(van.vehicle)[klass] < 1:
                continue
            for (prev_end, prev_node), (next_start, next_node) in _openings(van, shift):
                if prev_end + matrix[prev_node][job.home_node] > board:
                    continue
                deadhead = 0 if next_node < 0 else matrix[UNIT_NODE][next_node]
                if finish + deadhead > next_start:
                    continue
                _commit(
                    van,
                    _Task(
                        start=board,
                        end=finish,
                        start_node=job.home_node,
                        end_node=UNIT_NODE,
                        stops=[
                            RouteStop(
                                trip_id=job.trip.trip_id,
                                kind=StopKind.pickup,
                                node=job.home_node,
                                eta=to_hhmm(board),
                                load_after=aboard,
                            ),
                            RouteStop(
                                trip_id=job.trip.trip_id,
                                kind=StopKind.dropoff,
                                node=UNIT_NODE,
                                eta=to_hhmm(arrive),
                                load_after=empty,
                            ),
                        ],
                    ),
                )
                return True
    return False


def _dropoff_order(
    boarded: list[_Job],
    picked: dict[str, int],
    depart: int,
    matrix: list[list[int]],
    dwell: dict[str, int],
    broker: dict[str, Any],
) -> list[_Job] | None:
    best: tuple[int, list[_Job]] | None = None
    for order in permutations(sorted(boarded, key=lambda job: job.trip.trip_id)):
        node = UNIT_NODE
        time = depart
        travelled = 0
        for job in order:
            travelled += matrix[node][job.home_node]
            time += matrix[node][job.home_node]
            node = job.home_node
            cap = min(broker["max_ride_min"], broker["max_ride_ratio"] * matrix[UNIT_NODE][node])
            if time - picked[job.trip.trip_id] > cap:
                break
            time += dwell[job.mobility]
        else:
            if best is None or travelled < best[0]:
                best = (travelled, list(order))
    return None if best is None else best[1]


def _serve_return(
    batch: list[_Job],
    arrive: int,
    matrix: list[list[int]],
    dwell: dict[str, int],
    rules: dict[str, Any],
) -> tuple[_Task | None, list[_Job], list[_Job]] | None:
    broker = rules["broker"]
    time = arrive
    load = {"ambulatory": 0, "wheelchair": 0, "stretcher": 0}
    stops: list[RouteStop] = []
    boarded: list[_Job] = []
    left: list[_Job] = []
    picked: dict[str, int] = {}
    for job in batch:
        time = max(time, job.service)
        if not job.requeued and job.ready > time + broker["driver_wait_min"]:
            left.append(job)
            continue
        time = max(time, job.ready)
        load[CLASS_OF[job.mobility]] += 1
        stops.append(
            RouteStop(
                trip_id=job.trip.trip_id,
                kind=StopKind.pickup,
                node=UNIT_NODE,
                eta=to_hhmm(time),
                load_after=Load(**load),
            )
        )
        picked[job.trip.trip_id] = time
        boarded.append(job)
        time += dwell[job.mobility]
    if not boarded:
        return None, [], left
    order = _dropoff_order(boarded, picked, time, matrix, dwell, broker)
    if order is None:
        return None
    node = UNIT_NODE
    for job in order:
        time += matrix[node][job.home_node]
        node = job.home_node
        load[CLASS_OF[job.mobility]] -= 1
        stops.append(
            RouteStop(
                trip_id=job.trip.trip_id,
                kind=StopKind.dropoff,
                node=node,
                eta=to_hhmm(time),
                load_after=Load(**load),
            )
        )
        time += dwell[job.mobility]
    return _Task(arrive, time, UNIT_NODE, node, stops), boarded, left


def _try_return(
    van: _Van,
    opening: tuple[tuple[int, int], tuple[int, int]],
    arrive: int,
    pending: list[_Job],
    matrix: list[list[int]],
    dwell: dict[str, int],
    rules: dict[str, Any],
    shift: tuple[int, int],
) -> tuple[_Task | None, list[_Job], list[_Job]] | None:
    if arrive > shift[1]:
        return None
    next_start, next_node = opening[1]

    def fits(task: _Task | None) -> bool:
        if task is None:
            return True
        deadhead = 0 if next_node < 0 else matrix[task.end_node][next_node]
        return task.end <= shift[1] and task.end + deadhead <= next_start

    head = pending[0]
    best = _serve_return([head], arrive, matrix, dwell, rules)
    if best is None or not fits(best[0]):
        return None
    capacity = _capacity(van.vehicle)
    load = {"ambulatory": 0, "wheelchair": 0, "stretcher": 0}
    load[CLASS_OF[head.mobility]] += 1
    batch = [head]
    waiting = [
        job
        for job in pending[1:]
        if job.service <= arrive + rules["synth"]["batch_window_min"]
    ]
    while waiting:
        taken = None
        for job in sorted(
            waiting,
            key=lambda j: (min(matrix[b.home_node][j.home_node] for b in batch), j.trip.trip_id),
        ):
            if load[CLASS_OF[job.mobility]] + 1 > capacity[CLASS_OF[job.mobility]]:
                continue
            trial = sorted(batch + [job], key=lambda j: (j.service, j.trip.trip_id))
            served = _serve_return(trial, arrive, matrix, dwell, rules)
            if served is None or served[0] is None or not fits(served[0]):
                continue
            taken = (job, trial, served)
            break
        if taken is None:
            break
        job, batch, best = taken
        load[CLASS_OF[job.mobility]] += 1
        waiting.remove(job)
    return best


def _place_returns(
    vans: list[_Van],
    jobs: list[_Job],
    matrix: list[list[int]],
    dwell: dict[str, int],
    rules: dict[str, Any],
    shift: tuple[int, int],
) -> list[_Job]:
    pending = sorted(jobs, key=lambda job: (job.service, job.trip.trip_id))
    queued: list[_Job] = []
    while pending:
        head = pending[0]
        candidates = sorted(
            (
                (
                    max(opening[0][0] + matrix[opening[0][1]][UNIT_NODE], head.service),
                    van.vehicle.vehicle_id,
                    van,
                    opening,
                )
                for van in vans
                for opening in _openings(van, shift)
            ),
            key=lambda item: (item[0], item[1]),
        )
        placed = None
        for arrive, _, van, opening in candidates:
            served = _try_return(van, opening, arrive, pending, matrix, dwell, rules, shift)
            if served is not None:
                placed = (arrive, van, served)
                break
        if placed is None:
            queued.append(head)
            pending.remove(head)
            continue
        arrive, van, (task, boarded, left) = placed
        if task is None:
            resume = arrive + rules["broker"]["driver_wait_min"]
        else:
            resume = task.end
            _commit(van, task)
        for job in boarded:
            pending.remove(job)
        for job in left:
            job.requeued = True
            job.service = max(job.ready, resume)
        pending.sort(key=lambda job: (job.service, job.trip.trip_id))
    return queued


def _routes(
    rules: dict[str, Any], vehicles: list[Vehicle], jobs: list[_Job], matrix: list[list[int]]
) -> list[Route]:
    dwell = rules["broker"]["dwell_min"]
    shift = window_min(vehicles[0].shift)
    vans = [_Van(vehicle=vehicle) for vehicle in vehicles]
    outbound = sorted(
        (job for job in jobs if job.trip.leg == Leg.to),
        key=lambda job: (job.chair_start, job.trip.trip_id),
    )
    floor = max(shift[0], to_min(rules["broker"]["earliest_pickup"]))
    for job in outbound:
        if not _place_to(vans, job, matrix, dwell, shift, floor):
            job.trip.status = TripStatus.queued
    per_shift = rules["synth"]["return_vans_per_shift"]
    for index, shift_id in enumerate(SHIFT_IDS):
        returns = [job for job in jobs if job.trip.leg == Leg.from_ and job.shift_id == shift_id]
        chosen = [vans[(index * per_shift + offset) % len(vans)] for offset in range(per_shift)]
        for job in _place_returns(chosen, returns, matrix, dwell, rules, shift):
            job.trip.status = TripStatus.queued
    by_trip = {job.trip.trip_id: job.trip for job in jobs}
    routes: list[Route] = []
    for van in vans:
        stops = [stop for task in van.tasks for stop in task.stops]
        if not stops:
            continue
        for index, stop in enumerate(stops):
            if stop.kind == StopKind.pickup:
                by_trip[stop.trip_id].vehicle_id = van.vehicle.vehicle_id
                by_trip[stop.trip_id].seq = index
        routes.append(Route(vehicle_id=van.vehicle.vehicle_id, stops=stops))
    return routes


def _events(rng: np.random.Generator, patients: list[Patient]) -> list[Event]:
    late = next(p for p in patients if p.patient_id == "P14")
    add_ons = [
        {
            "add_on_id": f"A{number}",
            "shift_id": SHIFT_IDS[int(rng.integers(1, len(SHIFT_IDS)))],
            "rx_duration_min": int(sorted(RX_COUNTS)[int(rng.integers(len(RX_COUNTS)))]),
            "mobility": ADD_ON_MOBILITY[int(rng.integers(len(ADD_ON_MOBILITY)))],
            "home_node": int(rng.integers(2, NODE_COUNT)),
        }
        for number in (1, 2)
    ]
    return [
        Event(t="13:40", type=EventType.vehicle_down, payload={"vehicle_id": "V3"}),
        Event(
            t="11:00",
            type=EventType.chair_down,
            payload={"chair_id": "C07", "window": ["11:00", "21:00"]},
        ),
        Event(
            t=late.start_time,
            type=EventType.late_arrival,
            payload={"patient_id": "P14", "delay_min": 35},
        ),
        Event(
            t="09:00",
            type=EventType.add_on_patient,
            payload={"patients": add_ons, "vehicle_unavailable": "V5"},
        ),
        Event(t="15:00", type=EventType.travel_slowdown, payload={"factor": 1.3}),
    ]


def _llm_note(client: Any, system: str, facts: dict[str, Any]) -> dict[str, str] | None:
    import anthropic

    try:
        response = client.messages.create(
            model=NOTE_MODEL,
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": json.dumps(facts, sort_keys=True)}],
            output_config={"format": {"type": "json_schema", "schema": NOTE_SCHEMA}},
        )
        text = next(block.text for block in response.content if block.type == "text")
        return json.loads(text)
    except (anthropic.AnthropicError, ValueError, TypeError, KeyError, StopIteration):
        return None


def _llm_notes(patients: list[Patient], riders: list[Rider]) -> None:
    import anthropic

    client = anthropic.Anthropic()
    system = (ROOT / "prompts" / "synth_notes.v1.md").read_text(encoding="utf-8")
    by_patient = {rider.patient_id: rider for rider in riders}
    for patient in patients:
        rider = by_patient.get(patient.patient_id)
        facts = {
            "patient_id": patient.patient_id,
            "shift": patient.shift_id.value,
            "chair_start": patient.start_time,
            "duration_min": int(patient.rx_duration_min),
            "mobility": patient.mobility.value,
            "flags": {
                "clinically_fixed": patient.clinically_fixed,
                "fixed_reason": patient.fixed_reason,
            },
            "hypotension": int(patient.recovery_buffer_min) == 35,
            "consent_to_move": patient.consent_to_move,
            "caregiver_window": None
            if rider is None or rider.caregiver_window is None
            else list(rider.caregiver_window.root),
            "language": "en" if rider is None else rider.language,
        }
        notes = _llm_note(client, system, facts)
        if notes is None:
            continue
        patient.display_name = notes["display_name"]
        patient.nurse_note = notes["nurse_note"]
        if rider is not None:
            rider.rider_note = notes["rider_note"]


def generate(seed: int, out_dir: Path, use_llm: bool = False) -> None:
    rules = _rules()
    rng = np.random.default_rng(seed)
    pool = json.loads((ROOT / "data" / "names.json").read_text(encoding="utf-8"))["names"]
    unit = _unit(seed, rules)
    travel = _travel(rng, seed)
    fleet = _fleet(seed, rules)
    slots = _slots(rng, rules)
    names = [str(n) for n in rng.choice(pool, len(slots), replace=False)]
    patients = _patients(rng, rules, slots, names)
    riders = _riders(rng, patients, travel.nodes)
    trips, jobs = _jobs(rng, rules, patients, riders)
    routes = _routes(rules, fleet.vehicles, jobs, travel.matrix)
    events = _events(rng, patients)
    if use_llm:
        _llm_notes(patients, riders)
    generator = LLM_GENERATOR if use_llm else GENERATOR
    for document in (unit, travel, fleet):
        document.generator = generator
    roster = Roster(
        synthetic=True, generator=generator, seed=seed, patients=patients, riders=riders
    )
    manifest = Manifest(
        synthetic=True,
        generator=generator,
        seed=seed,
        broker_policy_text=(ROOT / "config" / "broker_policy.md").read_text(encoding="utf-8"),
        trips=trips,
        routes=routes,
    )
    registry = _registry()
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, document in (
        ("unit", unit),
        ("roster", roster),
        ("manifest", manifest),
        ("fleet", fleet),
        ("travel", travel),
    ):
        _write(out_dir / f"{name}.json", document, _validator(registry, f"{name}.schema.json"))
    validator = _validator(registry, "event.schema.json")
    lines = []
    for event in events:
        payload = event.model_dump(mode="json")
        validator.validate(payload)
        lines.append(json.dumps(payload, sort_keys=True))
    (out_dir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--llm", action="store_true")
    args = parser.parse_args()
    generate(args.seed, Path(args.out), args.llm)
    print(f"synth seed {args.seed} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
