"""Describe stored AIS observations without interpreting their cause."""
from datetime import datetime
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel

LONG_INTERVAL_SECONDS = 15 * 60
MAX_INTERVAL_DETAILS = 10


class Interval(BaseModel):
    before: datetime
    after: datetime
    duration_seconds: float


class QualityReport(BaseModel):
    observed_points: int
    conflict_count: int
    clock_skew_count: int
    interval_status: Literal['assessed', 'truncated', 'insufficient']
    long_interval_threshold_seconds: int = LONG_INTERVAL_SECONDS
    long_interval_count: int | None = None
    long_intervals: list[Interval]


def assess_observations(points, *, truncated: bool) -> QualityReport:
    """Assess intervals between chronologically ordered stored positions only."""
    counts = {'observed_points':len(points), 'conflict_count':sum(point['time_conflict'] for point in points),
              'clock_skew_count':sum(point['clock_skew'] for point in points)}
    if truncated or len(points) < 2:
        return QualityReport(**counts, interval_status='truncated' if truncated else 'insufficient', long_intervals=[])
    total = 0
    details = []
    for a, b in pairwise(points):
        before, after = a['provider_time'], b['provider_time']
        seconds = (after - before).total_seconds()
        if seconds >= LONG_INTERVAL_SECONDS:
            total += 1
            if len(details) < MAX_INTERVAL_DETAILS:
                details.append(Interval(before=before, after=after, duration_seconds=seconds))
    return QualityReport(**counts, interval_status='assessed', long_interval_count=total, long_intervals=details)
