import json
from datetime import UTC, datetime

import pytest

from shadow_fleet.collector import BootstrapBuffer, BufferOverflow, snapshot_candidates
from shadow_fleet.transport import SnapshotError

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def feature(stamp):
    return {'type': 'Feature', 'id': '123456789',
            'geometry': {'type': 'Point', 'coordinates': [25, 60]},
            'properties': {'mmsi': '123456789', 'timestampExternal': stamp}}


def test_bootstrap_watermark_preserves_messages_arriving_after_snapshot():
    queue = BootstrapBuffer(epoch=1, max_messages=3)
    a = json.dumps({'lon': 25, 'lat': 60, 'time': int(NOW.timestamp())}).encode()
    queue.push(1, 'vessels-v2/123456789/location', a, NOW, retained=False)
    watermark = queue.watermark()
    queue.push(1, 'vessels-v2/123456789/location', a, NOW, retained=False)
    prefix = queue.take_through(watermark)
    assert [e.sequence for e in prefix] == [1]
    assert [e.sequence for e in queue.take_through(queue.watermark())] == [2]


def test_overflow_fails_closed_and_old_epoch_is_rejected():
    queue = BootstrapBuffer(epoch=2, max_messages=1)
    queue.push(2, 'topic', b'a', NOW, retained=False)
    with pytest.raises(BufferOverflow):
        queue.push(2, 'topic', b'b', NOW, retained=False)
    with pytest.raises(BufferOverflow):
        queue.take_through(queue.watermark())
    assert queue.push(1, 'topic', b'a', NOW, retained=False) is False


def test_all_invalid_snapshot_fails_but_empty_or_expired_is_allowed():
    assert snapshot_candidates([], NOW) == []
    assert snapshot_candidates([feature(0)], NOW) == []
    with pytest.raises(SnapshotError):
        snapshot_candidates([{'type': 'Feature'}], NOW)


def test_stream_marks_only_valid_nonretained_delivery_live():
    from shadow_fleet.collector import stream_candidates

    queue = BootstrapBuffer(epoch=1)
    payload = json.dumps({'lon': 25, 'lat': 60, 'time': int(NOW.timestamp())}).encode()
    queue.push(1, 'vessels-v2/123456789/location', payload, NOW, retained=True)
    candidates, live_at = stream_candidates(queue.take_through(queue.watermark()))
    assert len(candidates) == 1 and live_at is None
    queue.push(1, 'vessels-v2/123456789/location', payload, NOW, retained=False)
    candidates, live_at = stream_candidates(queue.take_through(queue.watermark()))
    assert len(candidates) == 1 and live_at == NOW


def test_inflight_counts_against_queue_limit_until_ack():
    queue = BootstrapBuffer(epoch=1, max_messages=1)
    queue.push(1, 'topic', b'a', NOW, retained=False)
    batch = queue.take_through(queue.watermark())
    queue.acknowledge(batch)
    assert queue.push(1, 'topic', b'b', NOW, retained=False)


def test_bootstrap_commits_snapshot_and_prefix_without_losing_later_push():
    from shadow_fleet.collector import commit_bootstrap

    queue = BootstrapBuffer(epoch=7)
    payload = json.dumps({'lon': 25, 'lat': 60, 'time': int(NOW.timestamp())}).encode()
    queue.push(7, 'vessels-v2/123456789/location', payload, NOW, retained=False)

    class Store:
        epoch = 7
        def apply_batch(self, positions, *, epoch, state, now, commit_guard=None):
            assert epoch == 7
            assert {p.transport for p in positions} == {'rest', 'mqtt'}
            assert state.sync_state == 'live'
            queue.push(7, 'vessels-v2/123456789/location', payload, NOW, retained=False)

    commit_bootstrap(Store(), queue, [feature(int(NOW.timestamp() * 1000))], NOW, NOW)
    assert [e.sequence for e in queue.take_through(queue.watermark())] == [2]


def test_failed_bootstrap_discards_epoch_queue():
    from shadow_fleet.collector import commit_bootstrap

    queue = BootstrapBuffer(epoch=7)
    queue.push(7, 'topic', b'{}', NOW, retained=False)
    class Store:
        epoch = 7
        def apply_batch(self, *args, **kwargs):
            raise RuntimeError('database failed')

    with pytest.raises(RuntimeError, match='database failed'):
        commit_bootstrap(Store(), queue, [], NOW, NOW)
    with pytest.raises(BufferOverflow):
        queue.take_through(queue.watermark())


def test_old_push_does_not_make_bootstrap_live():
    from datetime import timedelta
    from shadow_fleet.collector import commit_bootstrap

    queue = BootstrapBuffer(epoch=1)
    payload = json.dumps({'lon': 25, 'lat': 60, 'time': int(NOW.timestamp())}).encode()
    queue.push(1, 'vessels-v2/123456789/location', payload, NOW, retained=False)
    class Store:
        def apply_batch(self, positions, *, epoch, state, now, commit_guard=None):
            assert state.sync_state == 'syncing'
    commit_bootstrap(Store(), queue, [], NOW, NOW + timedelta(seconds=61))


def test_stream_batch_marks_nonretained_duplicate_live_and_limits_batch():
    from shadow_fleet.collector import apply_stream_batch
    from shadow_fleet.store import SourceStateUpdate
    queue = BootstrapBuffer(epoch=3)
    payload = json.dumps({'lon': 25, 'lat': 60, 'time': int(NOW.timestamp())}).encode()
    for _ in range(3):
        queue.push(3, 'vessels-v2/123456789/location', payload, NOW, retained=False)
    class Store:
        def apply_batch(self, positions, *, epoch, state, now, commit_guard=None):
            assert len(positions) == 2
            assert state.sync_state == 'live'
            assert state.last_mqtt_at == NOW
    state = SourceStateUpdate('syncing', NOW, NOW, None, None)
    result = apply_stream_batch(Store(), queue, state, NOW, max_messages=2)
    assert result.sync_state == 'live'
    assert len(queue.take_through(queue.watermark())) == 1


def test_failed_stream_commit_marks_queue_failed():
    from shadow_fleet.collector import apply_stream_batch
    from shadow_fleet.store import SourceStateUpdate
    queue = BootstrapBuffer(epoch=3)
    queue.push(3, 'topic', b'{}', NOW, retained=False)
    class Store:
        def apply_batch(self, *args, **kwargs):
            raise RuntimeError('connection lost')
    with pytest.raises(RuntimeError, match='connection lost'):
        apply_stream_batch(Store(), queue, SourceStateUpdate('syncing', NOW, None, None, None), NOW)
    with pytest.raises(BufferOverflow):
        queue.take_through(queue.watermark())


def test_collector_bootstrap_and_graceful_stop_degrades_source():
    from shadow_fleet.collector import Collector
    from shadow_fleet.transport import SnapshotEnvelope
    from threading import Event
    stop = Event()
    writes = []
    payload = json.dumps({'lon':25,'lat':60,'time':int(NOW.timestamp())}).encode()
    class Store:
        epoch = 2
        def apply_batch(self, positions, *, epoch, state, now, commit_guard=None):
            writes.append(state.sync_state)
            if state.sync_state == 'live':
                stop.set()
        def close(self): pass
    class Transport:
        def __init__(self, queue): self.queue, self.failed = queue, Event()
        def start(self): self.queue.push(2, 'vessels-v2/123456789/location', payload, NOW, retained=False)
        def close(self): pass
    service = Collector(store_factory=Store, transport_factory=Transport,
                        fetch=lambda: SnapshotEnvelope([], NOW), now=lambda: NOW)
    service.run(stop)
    assert writes == ['live', 'degraded']


def test_collector_reconnects_with_new_writer_epoch_after_disconnect():
    from shadow_fleet.collector import Collector
    from shadow_fleet.transport import SnapshotEnvelope
    from threading import Event
    stop = Event()
    created = []
    states = []
    class Stop:
        def is_set(self): return stop.is_set()
        def wait(self, timeout): return stop.is_set()
    class Store:
        def __init__(self):
            self.epoch = len(created) + 1
            created.append(self.epoch)
        def apply_batch(self, positions, *, epoch, state, now, commit_guard=None):
            states.append((epoch, state.sync_state))
            if epoch == 2 and state.sync_state == 'syncing':
                stop.set()
        def close(self): pass
    class Transport:
        def __init__(self, queue): self.failed, self.queue = Event(), queue
        def start(self):
            if self.queue.epoch == 1:
                raise RuntimeError('disconnected')
        def close(self): pass
    Collector(store_factory=Store, transport_factory=Transport,
              fetch=lambda: SnapshotEnvelope([], NOW), now=lambda: NOW,
              jitter=lambda a,b: 0).run(Stop())
    assert created == [1, 2]
    assert states == [(1, 'degraded'), (2, 'syncing'), (2, 'degraded')]


def test_collector_closes_writer_when_transport_close_fails():
    from shadow_fleet.collector import Collector
    from shadow_fleet.transport import SnapshotEnvelope
    from threading import Event
    stop, closed = Event(), []
    class Store:
        epoch = 1
        def apply_batch(self, positions, *, epoch, state, now, commit_guard=None):
            if state.sync_state == 'syncing':
                stop.set()
        def close(self): closed.append(True)
    class Transport:
        def __init__(self, queue): self.failed = Event()
        def start(self): pass
        def close(self): raise RuntimeError('transport close failed')
    Collector(store_factory=Store, transport_factory=Transport,
              fetch=lambda: SnapshotEnvelope([], NOW), now=lambda: NOW).run(stop)
    assert closed == [True]


def test_no_push_for_sixty_seconds_reconnects_and_marks_degraded():
    from shadow_fleet.collector import Collector
    from shadow_fleet.transport import SnapshotEnvelope
    from threading import Event
    clock = [0.0]
    stop = Event()
    states = []
    epochs = []
    class Stop:
        def is_set(self): return stop.is_set()
        def wait(self, seconds):
            clock[0] += seconds
            return stop.is_set()
    class Store:
        def __init__(self):
            self.epoch = len(epochs) + 1
            epochs.append(self.epoch)
        def apply_batch(self, positions, *, epoch, state, now, commit_guard=None):
            states.append((epoch, state.sync_state))
            if epoch == 2 and state.sync_state == 'syncing':
                stop.set()
        def close(self): pass
    class Transport:
        def __init__(self, queue): self.failed = Event()
        def start(self): pass
        def close(self): pass
    Collector(store_factory=Store, transport_factory=Transport,
              fetch=lambda: SnapshotEnvelope([], NOW), now=lambda: NOW,
              monotonic=lambda: clock[0], jitter=lambda a,b: 0).run(Stop())
    assert epochs == [1,2]
    assert (1, 'degraded') in states
    assert all(state != 'live' for _, state in states)


def test_stop_during_subscription_does_not_start_snapshot():
    from shadow_fleet.collector import Collector
    from threading import Event
    stop = Event()
    called = []
    class Store:
        epoch = 1
        def apply_batch(self, positions, *, epoch, state, now): pass
        def close(self): pass
    class Transport:
        def __init__(self, queue): self.failed = Event()
        def start(self): stop.set()
        def close(self): pass
    def fetch():
        called.append(True)
        raise AssertionError('snapshot should not be requested')
    Collector(store_factory=Store, transport_factory=Transport, fetch=fetch, now=lambda: NOW).run(stop)
    assert called == []


def test_repeated_disconnect_after_bootstrap_increases_backoff():
    from shadow_fleet.collector import Collector
    from shadow_fleet.transport import SnapshotEnvelope
    from threading import Event
    stopped = Event()
    waits, epochs = [], []
    class Stop:
        def is_set(self): return stopped.is_set()
        def wait(self, seconds):
            waits.append(seconds)
            return stopped.is_set()
    class Store:
        def __init__(self):
            self.epoch = len(epochs) + 1
            epochs.append(self.epoch)
        def apply_batch(self, positions, *, epoch, state, now, commit_guard=None): pass
        def close(self): pass
    class Transport:
        def __init__(self, queue):
            self.failed = Event()
        def start(self):
            if len(epochs) == 4:
                stopped.set()
        def close(self): pass
    def fetch():
        transport_failure.set()
        return SnapshotEnvelope([], NOW)
    transport_failure = Event()
    class FailingTransport(Transport):
        def __init__(self, queue):
            super().__init__(queue)
            self.failed = transport_failure
            self.failed.clear()
    Collector(store_factory=Store, transport_factory=FailingTransport,
              fetch=fetch, now=lambda: NOW, jitter=lambda a,b:a).run(Stop())
    assert waits == [2, 4, 8]
