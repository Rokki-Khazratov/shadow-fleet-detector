"""Seed an isolated *_test database via a synthetic collector; never call live APIs."""
import json
import os
from datetime import UTC, datetime
from threading import Event

from psycopg.conninfo import conninfo_to_dict

from shadow_fleet.collector import Collector
from shadow_fleet.store import WriterSession, migrate
from shadow_fleet.transport import SnapshotEnvelope

url = os.environ['SFD_TEST_DATABASE_URL']
if not conninfo_to_dict(url).get('dbname', '').endswith('_test'):
    raise SystemExit('Test database name must end in _test')
migrate(url)
now = datetime.now(UTC)
stop = Event()


class Store:
    def __init__(self):
        self.session = WriterSession.open(url, 'fintraffic', record_history=True)
        self.epoch = self.session.epoch

    def apply_batch(self, positions, *, epoch, state, now, commit_guard=None):
        result = self.session.apply_batch(positions, epoch=epoch, state=state, now=now,
                                          commit_guard=commit_guard)
        if state.sync_state == 'live':
            stop.set()
        return result

    def close(self):
        self.session.close()


class Transport:
    def __init__(self, queue):
        self.queue = queue
        self.failed = Event()

    def start(self):
        data = json.dumps({'time': int(now.timestamp()), 'lon': 25, 'lat': 60, 'sog': 0}).encode()
        self.queue.push(self.queue.epoch, 'vessels-v2/987654321/location', data, now, retained=False)

    def close(self):
        pass


Collector(store_factory=Store, transport_factory=Transport,
          fetch=lambda: SnapshotEnvelope([], now), now=lambda: now).run(stop)
print('Synthetic collector message committed')
