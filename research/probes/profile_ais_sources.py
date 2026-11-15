"""Small, read-only AIS research run. Prints aggregates; never saves AIS rows."""
import concurrent.futures
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import statistics
import time
import urllib.error
import urllib.request

BASE = "https://meri.digitraffic.fi"
KYST = "https://kystdatahuset.kystverket.no/ws"
LIMIT = 8_000_000
SNAPSHOT_COUNT = 3  # fixed to keep this experiment small


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def fetch(url):
    start = time.monotonic()
    meta = {"url": url, "requested_at_utc": utcnow().isoformat()}
    payload = None
    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": "ShadowFleetDetector-research/0.1",
            "Digitraffic-User": "ShadowFleetDetector/research",
        })
        try:
            response = urllib.request.urlopen(req, timeout=12)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            meta.update(http_status=response.status, server_date=response.headers.get("Date"))
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError("wire byte limit exceeded")
            meta["wire_bytes"] = len(raw)
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                    raw = stream.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError("decoded byte limit exceeded")
            meta.update(body_bytes=len(raw), body_sha256=hashlib.sha256(raw).hexdigest())
        if not 200 <= meta["http_status"] < 300:
            meta["outcome"] = "http_error"
        else:
            payload = json.loads(raw)
            meta["outcome"] = "json_received"
    except json.JSONDecodeError:
        meta["outcome"] = "invalid_json"
    except (ValueError, EOFError, gzip.BadGzipFile) as exc:
        meta.update(outcome="body_error", error_type=type(exc).__name__)
    except OSError as exc:
        meta.update(outcome="transport_error", error_type=type(exc).__name__)
    at = utcnow()
    meta.update(received_at_utc=at.isoformat(), elapsed_s=round(time.monotonic() - start, 3))
    return meta, payload, at


def profile_positions(payload, as_of):
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ValueError("expected GeoJSON features list")
    features = payload["features"]
    ages = []
    valid_coords = set()
    latest = {}
    seen = set()
    counts = dict.fromkeys((
        "invalid_mmsi_rows", "invalid_coordinate_rows", "missing_provider_time_rows",
        "future_provider_time_rows", "ais_time_60_to_63_rows", "heading_511_rows",
        "sog_102_3_rows", "cog_360_rows", "same_mmsi_time_coordinates_repeated",
        "timestamp_field_outside_0_to_63_or_missing_rows",
    ), 0)
    for feature in features:
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        xy = geom.get("coordinates")
        valid = (geom.get("type") == "Point" and isinstance(xy, list) and len(xy) >= 2
                 and all(type(x) in (int, float) and math.isfinite(x) for x in xy[:2])
                 and -180 <= xy[0] <= 180 and -90 <= xy[1] <= 90)
        if valid:
            valid_coords.add((math.floor(xy[0]), math.floor(xy[1])))
        else:
            counts["invalid_coordinate_rows"] += 1
        mmsi = props.get("mmsi")
        valid_id = type(mmsi) is int and 100_000_000 <= mmsi <= 999_999_999
        if not valid_id:
            counts["invalid_mmsi_rows"] += 1
        stamp = props.get("timestampExternal")
        if type(stamp) is int and stamp > 0:
            age = (as_of.timestamp() * 1000 - stamp) / 1000
            ages.append(age)
            if age < 0:
                counts["future_provider_time_rows"] += 1
            if valid and valid_id:
                signature = (mmsi, stamp, xy[0], xy[1])
                if signature in seen:
                    counts["same_mmsi_time_coordinates_repeated"] += 1
                seen.add(signature)
                latest[mmsi] = max(latest.get(mmsi, stamp), stamp)
        else:
            counts["missing_provider_time_rows"] += 1
        sec = props.get("timestamp")
        if type(sec) is not int or not 0 <= sec <= 63:
            counts["timestamp_field_outside_0_to_63_or_missing_rows"] += 1
        elif sec >= 60:
            counts["ais_time_60_to_63_rows"] += 1
        counts["heading_511_rows"] += props.get("heading") == 511
        counts["sog_102_3_rows"] += props.get("sog") == 102.3
        counts["cog_360_rows"] += props.get("cog") == 360
    ages.sort()
    return {
        "rows": len(features), "mmsi_with_valid_point_and_provider_time": len(latest),
        "observed_one_degree_cell_count": len(valid_coords),
        "provider_record_age_seconds": {
            "n": len(ages),
            "median": round(statistics.median(ages), 3) if ages else None,
            "p95_nearest_rank": round(ages[math.ceil(.95 * len(ages)) - 1], 3) if ages else None,
            "over_300s": sum(x > 300 for x in ages),
            "over_3600s": sum(x > 3600 for x in ages),
        }, **counts,
    }, latest


def brief_kyst(payload):
    if not isinstance(payload, (list, dict)):
        raise ValueError("expected JSON object or array")
    if isinstance(payload, list):
        return {"response_shape": "array", "rows": len(payload),
                "item_keys": sorted(payload[0]) if payload and isinstance(payload[0], dict) else []}
    stats = {"response_shape": "object", "top_level_keys": sorted(payload)}
    if isinstance(payload.get("features"), list):
        features = payload["features"]
        stats.update(rows=len(features), response_shape="geojson_features",
                     first_properties_keys=sorted((features[0].get("properties") or {})) if features else [])
    return stats


def survey():
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        other = [
            pool.submit(fetch, KYST + "/api/ais/realtime/geojson"),
            pool.submit(fetch, KYST + "/api/ais/realtime/vessels-by-type"),
        ]
        snapshots = []
        previous = None
        for index in range(SNAPSHOT_COUNT):
            if index:
                time.sleep(25)
            meta, payload, at = fetch(BASE + "/api/ais/v1/locations")
            if payload is not None:
                try:
                    stats, current = profile_positions(payload, at)
                    meta["profile"] = stats
                    if previous is not None:
                        shared = current.keys() & previous.keys()
                        meta["vs_previous_successful_snapshot"] = {
                            "shared_mmsi": len(shared),
                            "with_newer_record_time": sum(current[key] > previous[key] for key in shared),
                            "same_record_time": sum(current[key] == previous[key] for key in shared),
                            "with_older_record_time": sum(current[key] < previous[key] for key in shared),
                            "new_mmsi": len(current.keys() - previous.keys()),
                            "missing_mmsi": len(previous.keys() - current.keys()),
                        }
                    previous = current
                except (AttributeError, TypeError, ValueError) as exc:
                    meta.update(outcome="schema_mismatch", error_type=type(exc).__name__)
            snapshots.append(meta)
        kyst = []
        for future in other:
            meta, payload, _ = future.result()
            if payload is not None:
                try:
                    meta["profile"] = brief_kyst(payload)
                except (AttributeError, TypeError, ValueError) as exc:
                    meta.update(outcome="schema_mismatch", error_type=type(exc).__name__)
            kyst.append(meta)
    return {"method_version": 1, "digitraffic": snapshots, "kystverket": kyst,
            "data_saved": "aggregates only",
            "digitraffic_attribution": "Fintraffic / digitraffic.fi — CC BY 4.0; aggregates",
            "kystverket_attribution": "Kystverket — NLOD; aggregates"}


if __name__ == "__main__":
    print(json.dumps(survey(), indent=2, allow_nan=False))
