from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import reduce
from itertools import permutations

import pytest

from shadow_fleet.fintraffic import normalize_mqtt, normalize_rest_feature
from shadow_fleet.reconcile import merge_position

NOW = datetime(2026, 11, 14, 18, 0, 2, tzinfo=UTC)
STAMP = int(NOW.timestamp())


def rest(ms, lon=25):
    return normalize_rest_feature(
        {"type": "Feature", "id": 123, "geometry": {"type": "Point", "coordinates": [lon, 60]},
         "properties": {"mmsi": 123, "timestampExternal": STAMP * 1000 + ms}},
        received_at=NOW + timedelta(seconds=1))


def mqtt(lon=25):
    return normalize_mqtt("vessels-v2/000000123/location",
                          {"time": STAMP, "lon": lon, "lat": 60},
                          received_at=NOW + timedelta(seconds=1))


def test_permutations_and_repeated_delivery():
    candidates = [rest(100), rest(900), mqtt(26)]
    results = [reduce(merge_position, order, None) for order in permutations(candidates)]
    assert all(result == results[0] for result in results)
    assert results[0].position == candidates[2]
    assert results[0].time_conflict
    assert reduce(merge_position, candidates * 2, None) == results[0]


def test_bucket_and_key():
    current = merge_position(None, mqtt())
    older = replace(current.position, provider_bucket=current.position.provider_bucket - 1)
    assert merge_position(current, older) == current
    newer = replace(current.position, provider_bucket=current.position.provider_bucket + 1)
    assert not merge_position(replace(current, time_conflict=True), newer).time_conflict
    with pytest.raises(ValueError):
        merge_position(current, replace(current.position, mmsi="999999999"))


def test_same_content_and_earliest_receipt():
    item = mqtt()
    current = merge_position(None, rest(0))
    assert not merge_position(current, item).time_conflict
    early = replace(item, received_at=NOW - timedelta(seconds=1), clock_skew=True)
    assert merge_position(merge_position(None, item), early).position == early
    assert merge_position(merge_position(None, early), item).position == early
