import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from .model import NormalizedPosition, NormalizeResult, Reject


def canonical_fingerprint(lon, lat, sog_kn, cog_deg, heading_deg):
    values = [float(v) if v is not None and v != 0 else (0.0 if v is not None else None)
              for v in (lon, lat, sog_kn, cog_deg, heading_deg)]
    return hashlib.sha256(json.dumps(values, separators=(",", ":"), allow_nan=False).encode()).digest()


def _id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value).zfill(9) if 0 <= value <= 999999999 else None
    if isinstance(value, str) and len(value) == 9 and value.isascii() and value.isdigit():
        return value
    return None


def _number(value, low, high, inclusive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    if not math.isfinite(value) or value < low or (value > high if inclusive else value >= high):
        return None
    return value or 0.0


def _normalize(mmsi, lon, lat, stamp, fields, received_at, transport):
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    received_at = received_at.astimezone(UTC)
    lon = _number(lon, -180, 180, True)
    lat = _number(lat, -90, 90, True)
    if lon is None or lat is None:
        return Reject("invalid_coordinate")
    lon = -180.0 if lon == 180 else lon
    if isinstance(stamp, bool) or not isinstance(stamp, int):
        return Reject("invalid_time")
    try:
        seconds, millis = (divmod(stamp, 1000) if transport == "rest" else (stamp, 0))
        provider = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds, milliseconds=millis)
    except (OverflowError, ValueError):
        return Reject("invalid_time")
    delta = provider - received_at
    if delta > timedelta(seconds=60):
        return Reject("future_time")
    if delta < -timedelta(hours=24):
        return Reject("expired")
    sog = _number(fields.get("sog"), 0, 102.3)
    cog = _number(fields.get("cog"), 0, 360)
    heading = _number(fields.get("heading"), 0, 359, True)
    if heading is not None and not heading.is_integer():
        heading = None
    return NormalizedPosition("fintraffic", mmsi, lon, lat, provider, seconds,
                              "millisecond" if transport == "rest" else "second",
                              received_at, transport, sog, cog, heading,
                              canonical_fingerprint(lon, lat, sog, cog, heading), delta > timedelta(0))


def normalize_rest_feature(feature, *, received_at) -> NormalizeResult:
    if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
        return Reject("invalid_shape")
    props, geom = feature.get("properties"), feature.get("geometry")
    if not isinstance(props, Mapping) or not isinstance(geom, Mapping) or geom.get("type") != "Point":
        return Reject("invalid_shape")
    coords = geom.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) != 2:
        return Reject("invalid_shape")
    mmsi = _id(props.get("mmsi"))
    if mmsi is None or ("id" in feature and _id(feature["id"]) is None):
        return Reject("invalid_id")
    if "id" in feature and _id(feature["id"]) != mmsi:
        return Reject("id_mismatch")
    return _normalize(mmsi, *coords, props.get("timestampExternal"), props, received_at, "rest")


def normalize_mqtt(topic, payload, *, received_at) -> NormalizeResult:
    if not isinstance(topic, str) or not isinstance(payload, Mapping):
        return Reject("invalid_shape")
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "vessels-v2" or parts[2] != "location":
        return Reject("invalid_shape")
    mmsi = _id(parts[1])
    if mmsi is None or ("mmsi" in payload and _id(payload["mmsi"]) is None):
        return Reject("invalid_id")
    if "mmsi" in payload and _id(payload["mmsi"]) != mmsi:
        return Reject("id_mismatch")
    return _normalize(mmsi, payload.get("lon"), payload.get("lat"), payload.get("time"),
                      payload, received_at, "mqtt")
