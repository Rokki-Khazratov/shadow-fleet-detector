"""Bounded public AIS probe; only aggregate statistics leave memory."""
import argparse
import concurrent.futures
import datetime as dt
import json
import math
import re
import statistics
import threading
import time
import uuid

import paho.mqtt.client as mqtt

from profile_ais_sources import BASE, KYST, fetch, profile_positions, utcnow

FIN = BASE + "/api/ais/v1/locations"
NOR = KYST + "/api/ais/realtime/geojson"
TOPICS = ("vessels-v2/+/location", "vessels-v2/+/locations")
MAX_PACKETS = 20_000


def ages(values):
    ordered = sorted(values)
    if not ordered:
        return {"n": 0}
    return {
        "n": len(ordered),
        "p50_s": round(statistics.median(ordered), 3),
        "p95_s": round(ordered[math.ceil(.95 * len(ordered)) - 1], 3),
        "over_300s": sum(x > 300 for x in ordered),
        "over_3600s": sum(x > 3600 for x in ordered),
        "future": sum(x < 0 for x in ordered),
    }


def norway_time(stamp):
    # Python 3.9 fromisoformat rejects some ISO fractional precisions (e.g. 4–5 digits).
    stamp = re.sub(r"\.(\d{1,7})(?=Z|[+-]\d\d:\d\d|$)",
                   lambda match: "." + match[1][:6].ljust(6, "0"), stamp)
    parsed = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return parsed, parsed.tzinfo is None


def norway():
    meta, body, at = fetch(NOR)
    if body is None:
        return meta
    if not isinstance(body, dict) or not isinstance(body.get("features"), list):
        return dict(meta, outcome="schema_mismatch")
    records = body["features"]
    values, identifiers = [], set()
    missing, invalid_id, assumed_utc = 0, 0, 0
    representations, classes = {}, {}
    for record in records:
        props = record.get("properties") or {}
        key = str(props.get("mmsi"))
        if re.fullmatch(r"[0-9]{9}", key):
            identifiers.add(key)
        else:
            invalid_id += 1
        cls = str(props.get("ais_class"))
        classes[cls if cls in ("A", "B", "1", "2") else "other_or_missing"] = classes.get(
            cls if cls in ("A", "B", "1", "2") else "other_or_missing", 0) + 1
        stamp = props.get("date_time_utc")
        form = type(stamp).__name__
        representations[form] = representations.get(form, 0) + 1
        try:
            parsed, naive = norway_time(stamp)
            if naive:
                assumed_utc += 1
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            values.append((at - parsed).total_seconds())
        except (AttributeError, TypeError, ValueError, OverflowError):
            missing += 1
    return dict(meta, profile={
        "features": len(records), "distinct_mmsi_shaped_keys": len(identifiers),
        "invalid_mmsi_rows": invalid_id, "ais_class_counts": classes,
        "source_timestamp_age": ages(values), "unparsed_time_rows": missing,
        "naive_date_time_utc_treated_as_utc": assumed_utc,
        "timestamp_types": representations,
    })


def rest():
    meta, body, received = fetch(FIN)
    if body is None:
        return meta, {}
    try:
        stats, latest = profile_positions(body, received)
    except (ValueError, TypeError, AttributeError) as exc:
        return dict(meta, outcome="schema_mismatch", error_type=type(exc).__name__), {}
    return dict(meta, profile=stats), latest


def compare(seconds):
    state = {"started_at_utc": utcnow().isoformat(), "window_requested_s": seconds,
             "topics": TOPICS, "frames": 0, "live_by_topic_suffix": {}, "invalid_messages": 0,
             "retained_messages": 0, "frame_limit": MAX_PACKETS}
    messages, newest = [], {}
    shapes = set()
    ready, finished = threading.Event(), threading.Event()

    def connected(client, userdata, flags, reason, properties):
        state["connack"] = str(reason)
        if reason.is_failure:
            finished.set()
        else:
            client.subscribe([(topic, 0) for topic in TOPICS])

    def subscribed(client, userdata, mid, reasons, properties):
        state["suback"] = [str(r) for r in reasons]
        if any(not r.is_failure for r in reasons):
            ready.set()
        else:
            finished.set()

    def received(client, userdata, message):
        if state["frames"] >= MAX_PACKETS:
            return
        state["frames"] += 1
        if state["frames"] == MAX_PACKETS:
            finished.set()
        if message.retain:
            state["retained_messages"] += 1
            return
        try:
            key = message.topic.split("/")[1]
            if not ready.is_set() or not re.fullmatch(r"[0-9]{9}", key) or len(message.payload) > 16384:
                raise ValueError("unexpected message")
            body = json.loads(message.payload)
            stamp = body["time"]
            if type(stamp) is not int or stamp <= 0:
                raise ValueError("unexpected time")
            shapes.add(tuple(sorted(body)))
            suffix = message.topic.rsplit("/", 1)[1]
            state["live_by_topic_suffix"][suffix] = state["live_by_topic_suffix"].get(suffix, 0) + 1
            messages.append(utcnow().timestamp() - stamp)
            newest[key] = max(newest.get(key, stamp), stamp)
        except (ValueError, TypeError, KeyError, IndexError):
            state["invalid_messages"] += 1

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sfd-research-" + uuid.uuid4().hex[:10],
                         transport="websockets", protocol=mqtt.MQTTv311, reconnect_on_failure=False)
    client.tls_set()
    client.ws_set_options(path="/mqtt")
    client.connect_timeout = 10
    client.on_connect, client.on_subscribe, client.on_message = connected, subscribed, received
    initial, later = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        kyst_future = pool.submit(norway)
        try:
            client.connect("meri.digitraffic.fi", 443, keepalive=45)
            client.loop_start()
            deadline = time.monotonic() + 10
            while not (ready.is_set() or finished.is_set()) and time.monotonic() < deadline:
                ready.wait(.1)
            if ready.is_set():
                started = time.monotonic()
                state["window_started_at_utc"] = utcnow().isoformat()
                first = pool.submit(rest)
                finished.wait(seconds)
                state["window_elapsed_s"] = round(time.monotonic() - started, 3)
                state["window_ended_at_utc"] = utcnow().isoformat()
                client.disconnect()
                client.loop_stop()
                state["rest_start"], initial = first.result()
                state["rest_end"], later = rest()
                state["outcome"] = "live_messages" if messages else "subscribed_no_valid_live_messages"
            else:
                state["outcome"] = "subscription_rejected_or_timeout"
        except (OSError, ValueError, mqtt.WebsocketConnectionError) as exc:
            state.update(outcome="connection_error", error_type=type(exc).__name__)
        finally:
            client.disconnect()
            client.loop_stop()
        if "rest_start" not in state:
            state["rest_fallback"], _ = rest()
        kystverket = kyst_future.result()
    state["publish_timestamp_age"] = ages(messages)
    state["live_mmsi_count"] = len(newest)
    state["payload_key_sets"] = [list(group) for group in sorted(shapes)]
    for name, snapshot in (("rest_start", initial), ("rest_end", later)):
        if name not in state or "profile" not in state[name]:
            continue
        common = {str(i): t for i, t in snapshot.items() if str(i) in newest}
        # MQTT seconds vs REST milliseconds: compare only at second precision.
        state[name + "_comparison"] = {
            "common_mmsi": len(common),
            "mqtt_newer_second": sum(newest[i] > t // 1000 for i, t in common.items()),
            "same_second": sum(newest[i] == t // 1000 for i, t in common.items()),
            "rest_newer_second": sum(newest[i] < t // 1000 for i, t in common.items()),
        }
    return {"method_version": 1, "fintraffic": state, "kystverket": kystverket,
            "attribution": {"fintraffic": "Fintraffic / digitraffic.fi, CC BY 4.0; aggregated",
                            "kystverket": "Kystverket, NLOD; aggregated"}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, choices=range(10, 46), default=30, metavar="10–45")
    print(json.dumps(compare(parser.parse_args().seconds), indent=2, allow_nan=False))
