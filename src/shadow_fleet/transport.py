"""Bounded, network-independent decoding for Fintraffic snapshots."""
import asyncio
import json
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from threading import Event

import httpx
import paho.mqtt.client as mqtt

MAX_BODY = 8 * 1024 * 1024
MAX_FEATURES = 20_000
MAX_DEPTH = 16


class SnapshotError(ValueError):
    """The complete snapshot cannot safely be accepted."""


class RateLimited(SnapshotError):
    def __init__(self, retry_after):
        super().__init__('snapshot rate limited')
        self.retry_after = retry_after


@dataclass(frozen=True)
class SnapshotEnvelope:
    features: list
    received_at: datetime


def _reason_failed(code):
    failure = getattr(code, 'is_failure', None)
    return bool(failure) if failure is not None else code >= 128


class MqttTransport:
    """MQTT callbacks only enqueue messages; the caller owns database writes."""
    def __init__(self, queue, *, client=None, clock=lambda: datetime.now(UTC)):
        self.queue, self.clock = queue, clock
        self.client = client or mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                                            transport='websockets', reconnect_on_failure=False)
        self.connected = Event()
        self.subscribed = Event()
        self.failed = Event()
        self.closed = False
        self.subscription_id = None
        self.client.tls_set_context()
        self.client.ws_set_options(path='/mqtt', headers={'Digitraffic-User': 'Shadow-Fleet-Detector/0.1'})
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if (reason_code != 0 if isinstance(reason_code, int) else _reason_failed(reason_code)):
            self.failed.set()
            return
        self.connected.set()
        code, self.subscription_id = client.subscribe('vessels-v2/+/location', qos=0)
        if code != mqtt.MQTT_ERR_SUCCESS:
            self.failed.set()

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        if (mid != self.subscription_id or not reason_codes
                or any(_reason_failed(code) for code in reason_codes)):
            self.failed.set()
        else:
            self.subscribed.set()

    def _on_message(self, client, userdata, message):
        if self.closed or self.failed.is_set():
            return
        try:
            self.queue.push(self.queue.epoch, message.topic, bytes(message.payload),
                            self.clock(), retained=bool(message.retain))
        except RuntimeError:
            self.failed.set()
            client.disconnect()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        if not self.closed:
            self.queue.fail()
            self.failed.set()

    def start(self):
        self.client.connect_async('meri.digitraffic.fi', 443, keepalive=60)
        self.client.loop_start()
        if not self.connected.wait(10) or self.failed.is_set():
            raise SnapshotError('MQTT connection failed')
        if not self.subscribed.wait(10) or self.failed.is_set():
            raise SnapshotError('MQTT subscription failed')

    def close(self):
        self.closed = True
        self.client.disconnect()
        self.client.loop_stop()


def fetch_snapshot(*, transport=None, clock=lambda: datetime.now(UTC), deadline_seconds=15):
    """Fetch a snapshot with a cancellable total deadline and bounded raw body."""
    async def request():
        async with httpx.AsyncClient(transport=transport, timeout=deadline_seconds,
                                     follow_redirects=False) as client:
            async with client.stream('GET', 'https://meri.digitraffic.fi/api/ais/v1/locations',
                                     headers={'Accept-Encoding': 'gzip',
                                              'Digitraffic-User': 'Shadow-Fleet-Detector/0.1'}) as response:
                if response.status_code == 429:
                    raise RateLimited(retry_after_seconds(response.headers.get('Retry-After'), clock()))
                response.raise_for_status()
                pieces = []
                count = 0
                async for piece in response.aiter_raw(chunk_size=65536):
                    count += len(piece)
                    if count > MAX_BODY:
                        raise SnapshotError('network body exceeds limit')
                    pieces.append(piece)
                received_at = clock()
                features = parse_snapshot(b''.join(pieces), encoding=response.headers.get('Content-Encoding', 'identity').lower())
                return SnapshotEnvelope(features, received_at)

    async def bounded_request():
        return await asyncio.wait_for(request(), timeout=deadline_seconds)

    try:
        return asyncio.run(bounded_request())
    except TimeoutError as exc:
        raise SnapshotError('snapshot deadline exceeded') from exc
    except httpx.HTTPError as exc:
        raise SnapshotError('snapshot request failed') from exc


def read_bounded(stream, *, max_bytes: int = MAX_BODY) -> bytes:
    if max_bytes < 0:
        raise ValueError('max_bytes must be non-negative')
    chunks = []
    total = 0
    while True:
        chunk = stream.read(min(65536, max_bytes - total + 1))
        if not chunk:
            return b''.join(chunks)
        total += len(chunk)
        if total > max_bytes:
            raise SnapshotError('network body exceeds limit')
        chunks.append(chunk)


def parse_snapshot(body: bytes, *, encoding: str) -> list:
    if len(body) > MAX_BODY:
        raise SnapshotError('compressed body exceeds limit')
    if encoding == 'gzip':
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            decoded = decoder.decompress(body, MAX_BODY + 1)
            if len(decoded) > MAX_BODY or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
                raise SnapshotError('invalid or oversized gzip body')
            body = decoded
        except zlib.error as exc:
            raise SnapshotError('invalid gzip body') from exc
    elif encoding not in ('identity', ''):
        raise SnapshotError('unsupported content encoding')
    data = bounded_json(body)
    if not isinstance(data, dict) or data.get('type') != 'FeatureCollection':
        raise SnapshotError('invalid feature collection')
    features = data.get('features')
    if not isinstance(features, list) or len(features) > MAX_FEATURES:
        raise SnapshotError('invalid features')
    return features


def bounded_json(body: bytes):
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise SnapshotError('invalid JSON') from exc
    stack = [(data, 1)]
    while stack:
        obj, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise SnapshotError('JSON nesting exceeds limit')
        if isinstance(obj, dict):
            stack.extend((v, depth + 1) for v in obj.values())
        elif isinstance(obj, list):
            stack.extend((v, depth + 1) for v in obj)
    return data


def retry_after_seconds(header: str | None, now: datetime) -> float | None:
    if not header:
        return None
    if header.isascii() and header.isdigit():
        if len(header) > 9:
            return float('inf')
        return float(int(header))
    try:
        date = parsedate_to_datetime(header)
        if date.tzinfo is None:
            return None
        return max(0.0, (date - now).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return None
