import gzip
import json
from datetime import UTC, datetime

import pytest

from shadow_fleet.transport import SnapshotError, parse_snapshot, retry_after_seconds

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_snapshot_accepts_plain_and_gzip_and_empty_features():
    data = json.dumps({'type': 'FeatureCollection', 'features': []}).encode()
    assert parse_snapshot(data, encoding='identity') == []
    assert parse_snapshot(gzip.compress(data), encoding='gzip') == []


def test_snapshot_rejects_truncated_gzip_and_invalid_shape():
    with pytest.raises(SnapshotError):
        parse_snapshot(gzip.compress(b'{}')[:-4], encoding='gzip')
    with pytest.raises(SnapshotError):
        parse_snapshot(b'{"type":"FeatureCollection","features":{}}', encoding='identity')


def test_snapshot_enforces_decompressed_size_and_feature_count():
    body = json.dumps({'type': 'FeatureCollection', 'features': [None] * 20001}).encode()
    with pytest.raises(SnapshotError):
        parse_snapshot(body, encoding='identity')
    with pytest.raises(SnapshotError):
        parse_snapshot(gzip.compress(b' ' * (8 * 1024 * 1024 + 1)), encoding='gzip')


def test_snapshot_enforces_nesting_limit():
    body = b'{"type":"FeatureCollection","features":[],"other":' + b'[' * 18 + b'0' + b']' * 18 + b'}'
    with pytest.raises(SnapshotError):
        parse_snapshot(body, encoding='identity')


def test_retry_after_parses_seconds_and_http_date():
    assert retry_after_seconds('12', NOW) == 12
    assert retry_after_seconds('Thu, 01 Jan 2026 00:00:15 GMT', NOW) == 15
    assert retry_after_seconds('not-a-date', NOW) is None


def test_read_bounded_limits_network_bytes_before_decoding():
    from io import BytesIO
    from shadow_fleet.transport import read_bounded

    assert read_bounded(BytesIO(b'abc'), max_bytes=3) == b'abc'
    with pytest.raises(SnapshotError):
        read_bounded(BytesIO(b'abcd'), max_bytes=3)


def test_fetch_snapshot_uses_bounded_raw_stream_and_accepts_gzip():
    import httpx
    from shadow_fleet.transport import fetch_snapshot

    data = gzip.compress(b'{"type":"FeatureCollection","features":[]}')
    def handler(request):
        assert request.headers['digitraffic-user']
        return httpx.Response(200, headers={'Content-Encoding': 'gzip'}, stream=httpx.ByteStream(data))
    envelope = fetch_snapshot(transport=httpx.MockTransport(handler), clock=lambda: NOW)
    assert envelope.features == [] and envelope.received_at == NOW


def test_fetch_snapshot_reports_rate_limit_with_retry_after():
    import httpx
    from shadow_fleet.transport import RateLimited, fetch_snapshot

    transport = httpx.MockTransport(lambda r: httpx.Response(429, headers={'Retry-After': '12'}))
    with pytest.raises(RateLimited) as exc:
        fetch_snapshot(transport=transport, clock=lambda: NOW)
    assert exc.value.retry_after == 12


def test_mqtt_transport_subscribes_before_accepting_and_queues_messages():
    from types import SimpleNamespace
    from shadow_fleet.collector import BootstrapBuffer
    from shadow_fleet.transport import MqttTransport

    class FakeClient:
        def tls_set_context(self): pass
        def ws_set_options(self, **kwargs): assert kwargs['path'] == '/mqtt'
        def connect_async(self, host, port, keepalive): assert (host, port) == ('meri.digitraffic.fi', 443)
        def loop_start(self):
            self.on_connect(self, None, None, 0, None)
            self.on_subscribe(self, None, 1, [0], None)
        def subscribe(self, topic, qos):
            assert topic == 'vessels-v2/+/location'
            return (0, 1)
        def disconnect(self): pass
        def loop_stop(self): pass
    queue = BootstrapBuffer(8)
    client = FakeClient()
    transport = MqttTransport(queue, client=client, clock=lambda: NOW)
    transport.start()
    client.on_message(client, None, SimpleNamespace(topic='vessels-v2/123456789/location', payload=b'{}', retain=True))
    event = queue.take_through(queue.watermark())[0]
    assert event.epoch == 8 and event.retained is True and event.received_at == NOW
    transport.close()


def test_retry_after_huge_integer_does_not_overflow():
    import math
    assert math.isinf(retry_after_seconds('9' * 5000, NOW))


def test_snapshot_total_deadline_interrupts_slow_network():
    import asyncio
    import httpx
    from shadow_fleet.transport import fetch_snapshot
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0.2)
            yield b'{}'
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=SlowStream()))
    with pytest.raises(SnapshotError, match='deadline'):
        fetch_snapshot(transport=transport, deadline_seconds=0.02)


def test_mqtt_rejects_failed_connack_without_subscribing():
    from shadow_fleet.collector import BootstrapBuffer
    from shadow_fleet.transport import MqttTransport
    class FakeClient:
        def tls_set_context(self): pass
        def ws_set_options(self, **kwargs): pass
        def subscribe(self, *args, **kwargs): raise AssertionError('must not subscribe')
    client = FakeClient()
    transport = MqttTransport(BootstrapBuffer(1), client=client)
    client.on_connect(client, None, None, 1, None)
    assert transport.failed.is_set()


def test_fetch_snapshot_rejects_oversize_network_stream():
    import httpx
    from shadow_fleet.transport import fetch_snapshot
    class HugeStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(129):
                yield b'x' * 65536
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=HugeStream()))
    with pytest.raises(SnapshotError, match='network body exceeds limit'):
        fetch_snapshot(transport=transport)


def test_unexpected_disconnect_invalidates_epoch_queue():
    from shadow_fleet.collector import BootstrapBuffer, BufferOverflow
    from shadow_fleet.transport import MqttTransport
    class Client:
        def tls_set_context(self): pass
        def ws_set_options(self, **kwargs): pass
    client = Client()
    queue = BootstrapBuffer(1)
    transport = MqttTransport(queue, client=client)
    client.on_disconnect(client, None, None, 1, None)
    assert transport.failed.is_set()
    with pytest.raises(BufferOverflow):
        queue.take_through(queue.watermark())
