"""Safe primitives for the future snapshot/stream collector lifecycle."""
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
import random
from threading import Lock
import time

from .fintraffic import normalize_mqtt, normalize_rest_feature
from .model import Reject
from .store import SourceStateUpdate
from .transport import MqttTransport, RateLimited, SnapshotError, bounded_json, fetch_snapshot


class BufferOverflow(RuntimeError):
    pass


@dataclass(frozen=True)
class IncomingEnvelope:
    epoch: int
    sequence: int
    topic: str
    payload: bytes
    received_at: datetime
    retained: bool


class BootstrapBuffer:
    """Bounded, epoch-specific FIFO; extracted entries remain reserved until acknowledged."""
    def __init__(self, epoch: int, *, max_messages: int = 10_000, max_bytes: int = 8 * 1024 * 1024):
        self.epoch = epoch
        self.max_messages = max_messages
        self.max_bytes = max_bytes
        self._lock = Lock()
        self._items = deque()
        self._inflight = {}
        self._bytes = 0
        self._sequence = 0
        self._failed = False

    def push(self, epoch, topic, payload, received_at, *, retained):
        with self._lock:
            if epoch != self.epoch:
                return False
            if self._failed:
                raise BufferOverflow('epoch failed')
            if (len(payload) > 64 * 1024 or len(self._items) + len(self._inflight) >= self.max_messages
                    or self._bytes + len(payload) > self.max_bytes):
                self._failed = True
                self._items.clear()
                self._inflight.clear()
                self._bytes = 0
                raise BufferOverflow('queue limit exceeded')
            self._sequence += 1
            envelope = IncomingEnvelope(epoch, self._sequence, topic, payload, received_at, retained)
            self._items.append(envelope)
            self._bytes += len(payload)
            return True

    def watermark(self):
        with self._lock:
            return self._sequence

    def has_pending(self):
        with self._lock:
            if self._failed:
                raise BufferOverflow('epoch failed')
            return bool(self._items)

    def take_through(self, watermark, *, max_items=None):
        with self._lock:
            if self._failed:
                raise BufferOverflow('epoch failed')
            batch = []
            while (self._items and self._items[0].sequence <= watermark
                   and (max_items is None or len(batch) < max_items)):
                envelope = self._items.popleft()
                self._inflight[envelope.sequence] = envelope
                batch.append(envelope)
            return batch

    def acknowledge(self, entries):
        with self._lock:
            if self._failed:
                raise BufferOverflow('epoch failed')
            for entry in entries:
                old = self._inflight.pop(entry.sequence, None)
                if old is not None:
                    self._bytes -= len(old.payload)

    def fail(self):
        with self._lock:
            self._failed = True
            self._items.clear()
            self._inflight.clear()
            self._bytes = 0

    def acquire_commit(self):
        self._lock.acquire()
        if self._failed:
            self._lock.release()
            raise BufferOverflow('epoch failed')

    def release_commit(self):
        self._lock.release()


def snapshot_candidates(features, received_at):
    candidates = []
    invalid = 0
    for feature in features:
        result = normalize_rest_feature(feature, received_at=received_at)
        if isinstance(result, Reject):
            if result.code != 'expired':
                invalid += 1
        else:
            candidates.append(result)
    if features and not candidates and invalid:
        raise SnapshotError('snapshot_invalid')
    return candidates


def stream_candidates(entries):
    candidates = []
    live_at = None
    for entry in entries:
        try:
            payload = bounded_json(entry.payload)
        except SnapshotError:
            continue
        result = normalize_mqtt(entry.topic, payload, received_at=entry.received_at)
        if isinstance(result, Reject):
            continue
        candidates.append(result)
        if not entry.retained and (live_at is None or entry.received_at > live_at):
            live_at = entry.received_at
    return candidates, live_at


def commit_bootstrap(store, queue, features, received_at, now):
    """Commit the snapshot and the captured queue prefix in one store transaction."""
    try:
        snapshot = snapshot_candidates(features, received_at)
        prefix = queue.take_through(queue.watermark())
        stream, live_at = stream_candidates(prefix)
        fresh = live_at is not None and now - live_at <= timedelta(seconds=60)
        state = SourceStateUpdate('live' if fresh else 'syncing', now, received_at, live_at, None)
        store.apply_batch(snapshot + stream, epoch=queue.epoch, state=state, now=now,
                          commit_guard=queue)
        queue.acknowledge(prefix)
        return state
    except Exception:
        queue.fail()
        raise


def apply_stream_batch(store, queue, state, now, *, max_messages=250):
    try:
        entries = queue.take_through(queue.watermark(), max_items=max_messages)
        candidates, live_at = stream_candidates(entries)
        last_mqtt = max(filter(None, (state.last_mqtt_at, live_at)), default=None)
        active = last_mqtt is not None and now - last_mqtt <= timedelta(seconds=60)
        new_state = SourceStateUpdate('live' if active else 'syncing', now,
                                      state.last_snapshot_at, last_mqtt, None)
        store.apply_batch(candidates, epoch=queue.epoch, state=new_state, now=now,
                          commit_guard=queue)
        queue.acknowledge(entries)
        return new_state
    except Exception:
        queue.fail()
        raise


class Collector:
    """Owns each writer epoch and reconnects after a transport or database failure."""
    def __init__(self, *, store_factory, transport_factory=MqttTransport, fetch=fetch_snapshot,
                 now=lambda: datetime.now(UTC), monotonic=time.monotonic,
                 jitter=random.uniform, history_maintenance=False):
        self.store_factory, self.transport_factory, self.fetch = store_factory, transport_factory, fetch
        self.now, self.monotonic, self.jitter = now, monotonic, jitter
        self.history_maintenance = history_maintenance

    def run(self, stop_event):
        delay = 2.0
        while not stop_event.is_set():
            store = transport = queue = state = None
            retry_after = 0.0
            try:
                store = self.store_factory()
                queue = BootstrapBuffer(store.epoch)
                transport = self.transport_factory(queue)
                transport.start()
                if stop_event.is_set():
                    break
                started = self.monotonic()
                envelope = self.fetch()
                if transport.failed.is_set():
                    raise SnapshotError('MQTT disconnected during snapshot')
                state = commit_bootstrap(store, queue, envelope.features, envelope.received_at, self.now())
                heartbeat = last_prune = self.monotonic()
                next_history_prune = heartbeat
                last_push = heartbeat if state.last_mqtt_at else started
                previous_mqtt = state.last_mqtt_at
                while not stop_event.is_set():
                    if transport.failed.is_set():
                        raise SnapshotError('MQTT disconnected or queue failed')
                    current = self.monotonic()
                    if state.sync_state == 'live' and current - started >= 60:
                        delay = 2.0
                    if queue.has_pending():
                        state = apply_stream_batch(store, queue, state, self.now())
                        heartbeat = current
                        if state.last_mqtt_at != previous_mqtt:
                            last_push, previous_mqtt = current, state.last_mqtt_at
                    if current - last_push > 60:
                        raise SnapshotError('MQTT push timeout')
                    if current - heartbeat >= 5:
                        state = apply_stream_batch(store, queue, state, self.now())
                        heartbeat = current
                    if current - last_prune >= 900:
                        store.prune(now=self.now(), max_rows=1000)
                        last_prune = current
                    if self.history_maintenance and current >= next_history_prune:
                        store.prune_history(now=self.now())
                        next_history_prune = current + 60
                    stop_event.wait(0.5)
            except RateLimited as exc:
                retry_after = exc.retry_after or 0.0
                logging.warning('Collector rate limited')
            except Exception as exc:
                if isinstance(exc, RuntimeError) and str(exc) == 'writer_already_running':
                    raise
                logging.warning('Collector epoch stopped: %s', type(exc).__name__)
            finally:
                if queue is not None:
                    queue.fail()
                if transport is not None:
                    try:
                        transport.close()
                    except Exception:
                        logging.warning('Could not close MQTT transport')
                if store is not None:
                    try:
                        if state is None and hasattr(store, 'mark_degraded'):
                            store.mark_degraded(now=self.now(), error_code='collector_stopped')
                        else:
                            previous_snapshot = state.last_snapshot_at if state else None
                            previous_mqtt = state.last_mqtt_at if state else None
                            degraded = SourceStateUpdate('degraded', self.now(), previous_snapshot,
                                                         previous_mqtt, 'collector_stopped')
                            store.apply_batch([], epoch=store.epoch, state=degraded, now=self.now())
                    except Exception:
                        logging.warning('Could not update collector state')
                    finally:
                        store.close()
            if not stop_event.is_set():
                wait_for = max(retry_after, min(60.0, self.jitter(delay, delay * 1.2)))
                while wait_for > 0 and not stop_event.is_set():
                    part = min(wait_for, 60.0)
                    stop_event.wait(part)
                    wait_for -= part
                delay = min(delay * 2, 60)
