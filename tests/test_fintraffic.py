import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from shadow_fleet.fintraffic import canonical_fingerprint, normalize_mqtt, normalize_rest_feature

NOW = datetime(2026, 11, 14, 18, 0, 2, tzinfo=UTC)
STAMP = int(NOW.timestamp())


def mqtt(**overrides):
    return {"time": STAMP, "lon": 25, "lat": 60, "sog": 0, **overrides}


def rest(**overrides):
    return {"type": "Feature", "id": 123, "geometry": {"type": "Point", "coordinates": [25, 60]},
            "properties": {"mmsi": 123, "timestampExternal": STAMP * 1000, **overrides}}


def test_hash_and_valid_transports():
    expected = hashlib.sha256(b"[25.0,60.0,0.0,null,null]").digest()
    assert canonical_fingerprint(25, 60, 0, None, None) == expected
    item = normalize_mqtt("vessels-v2/000000123/location", mqtt(), received_at=NOW)
    assert item.mmsi == "000000123"
    assert item.sog_kn == 0.0 and item.fingerprint == expected
    assert item.provider_bucket == 1794679202 and not item.clock_skew
    assert normalize_rest_feature(rest(), received_at=NOW).mmsi == "000000123"


@pytest.mark.parametrize("field,value,code", [
    ("lon", True, "invalid_coordinate"), ("lon", float("nan"), "invalid_coordinate"),
    ("lon", float("inf"), "invalid_coordinate"), ("lon", 181, "invalid_coordinate"),
    ("lat", 91, "invalid_coordinate"), ("time", True, "invalid_time"),
    ("time", 1.5, "invalid_time"),
])
def test_rejects(field, value, code):
    assert normalize_mqtt("vessels-v2/000000123/location",
                          mqtt(**{field: value}), received_at=NOW).code == code


def test_id_and_optional_values():
    assert normalize_rest_feature(rest(mmsi=124), received_at=NOW).code == "id_mismatch"
    feature = rest()
    del feature["properties"]["timestampExternal"]
    assert normalize_rest_feature(feature, received_at=NOW).code == "invalid_time"
    item = normalize_mqtt("vessels-v2/000000123/location",
                          mqtt(lon=180, sog=102.3, cog=360, heading=511), received_at=NOW)
    assert item.lon == -180 and item.sog_kn is item.cog_deg is item.heading_deg is None


def test_time_boundaries():
    feature = rest()
    props = feature["properties"]
    props["timestampExternal"] = STAMP * 1000 + 60000
    assert normalize_rest_feature(feature, received_at=NOW).clock_skew
    props["timestampExternal"] += 1
    assert normalize_rest_feature(feature, received_at=NOW).code == "future_time"
    props["timestampExternal"] = STAMP * 1000 - 86400000
    assert normalize_rest_feature(feature, received_at=NOW).provider_time == NOW - timedelta(days=1)
    props["timestampExternal"] -= 1
    assert normalize_rest_feature(feature, received_at=NOW).code == "expired"
    with pytest.raises(ValueError):
        normalize_rest_feature(feature, received_at=NOW.replace(tzinfo=None))
