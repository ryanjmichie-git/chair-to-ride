"""Clock and percentile helpers shared by the generator, the metrics and the solver."""

from __future__ import annotations

import math
from collections.abc import Sequence
from functools import lru_cache

from c2r.models import Window


@lru_cache(maxsize=4096)  # the solver parses the same HH:MM strings millions of times per solve
def to_min(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def window_min(window: Window) -> tuple[int, int]:
    return to_min(window.root[0]), to_min(window.root[1])


def p90(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return float(ordered[min(math.ceil(0.9 * len(ordered)), len(ordered)) - 1])
