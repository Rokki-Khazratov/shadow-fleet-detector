"""Accelerated synthetic workload: 6,000 messages, no network or database."""
import json
import argparse
import resource
import time
from datetime import UTC, datetime

from shadow_fleet.collector import BootstrapBuffer, apply_stream_batch
from shadow_fleet.reconcile import merge_position
from shadow_fleet.store import SourceStateUpdate

now = datetime.now(UTC).replace(microsecond=0)
parser = argparse.ArgumentParser()
parser.add_argument('--realtime', action='store_true', help='run 6000 synthetic messages over 60 seconds')
args = parser.parse_args()
queue = BootstrapBuffer(1)
state = SourceStateUpdate('syncing', now, now, None, None)

class Store:
    def __init__(self):
        self.values = {}
        self.messages = 0
    def apply_batch(self, positions, *, epoch, state, now, commit_guard=None):
        self.messages += len(positions)
        for position in positions:
            self.values[position.mmsi] = merge_position(self.values.get(position.mmsi), position)

store = Store()
start = time.perf_counter()
peak_queue = 0
for batch in range(24):
    for i in range(250):
        n = batch * 250 + i
        mmsi = f'{n % 1000:09d}'
        payload = json.dumps({'lon':25, 'lat':60, 'time':int(now.timestamp())}).encode()
        queue.push(1, f'vessels-v2/{mmsi}/location', payload, now, retained=False)
    peak_queue = max(peak_queue, 250)
    state = apply_stream_batch(store, queue, state, now)
    if args.realtime:
        time.sleep(max(0, start + (batch + 1) * 2.5 - time.perf_counter()))
print(f'messages={store.messages} unique_keys={len(store.values)} batches=24 peak_queue={peak_queue}')
print(f'wall_seconds={time.perf_counter() - start:.3f} maxrss_native={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}')
