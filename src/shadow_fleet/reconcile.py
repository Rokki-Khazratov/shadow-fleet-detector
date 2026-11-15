from dataclasses import replace
from datetime import UTC, datetime

from .model import NormalizedPosition, ProjectedPosition

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _rank(position: NormalizedPosition) -> tuple[int, int, bytes]:
    if position.transport == "mqtt":
        return 1, 0, position.fingerprint
    delta = position.provider_time - _EPOCH
    millis = (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
    return 0, millis, position.fingerprint


def merge_position(
    current: ProjectedPosition | None, incoming: NormalizedPosition
) -> ProjectedPosition:
    if current is None:
        return ProjectedPosition(incoming, False)
    existing = current.position
    if (existing.source_id, existing.mmsi) != (incoming.source_id, incoming.mmsi):
        raise ValueError("cannot merge different source or MMSI")
    if incoming.provider_bucket > existing.provider_bucket:
        return ProjectedPosition(incoming, False)
    if incoming.provider_bucket < existing.provider_bucket:
        return current
    conflict = current.time_conflict or existing.fingerprint != incoming.fingerprint
    old_rank, new_rank = _rank(existing), _rank(incoming)
    if new_rank > old_rank:
        winner = incoming
    elif new_rank < old_rank:
        winner = existing
    else:
        received_at = min(existing.received_at, incoming.received_at)
        winner = replace(existing, received_at=received_at,
                         clock_skew=existing.provider_time > received_at)
    return ProjectedPosition(winner, conflict)
