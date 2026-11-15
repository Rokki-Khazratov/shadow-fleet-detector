from dataclasses import dataclass
from datetime import datetime
from typing import Literal

RejectCode = Literal["invalid_shape", "invalid_id", "id_mismatch", "invalid_coordinate",
                     "invalid_time", "future_time", "expired"]


@dataclass(frozen=True)
class Reject:
    code: RejectCode


@dataclass(frozen=True)
class NormalizedPosition:
    source_id: str
    mmsi: str
    lon: float
    lat: float
    provider_time: datetime
    provider_bucket: int
    time_precision: Literal["second", "millisecond"]
    received_at: datetime
    transport: Literal["rest", "mqtt"]
    sog_kn: float | None
    cog_deg: float | None
    heading_deg: float | None
    fingerprint: bytes
    clock_skew: bool


@dataclass(frozen=True)
class ProjectedPosition:
    position: NormalizedPosition
    time_conflict: bool


NormalizeResult = NormalizedPosition | Reject
