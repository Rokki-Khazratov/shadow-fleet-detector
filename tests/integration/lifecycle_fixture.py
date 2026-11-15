"""Manipulate only a disposable *_test database for browser lifecycle acceptance."""
import json
import os
import sys
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.conninfo import conninfo_to_dict

from shadow_fleet.collector import BootstrapBuffer, apply_stream_batch, commit_bootstrap
from shadow_fleet.store import SourceStateUpdate, WriterSession, migrate

url = os.environ['SFD_TEST_DATABASE_URL']
if not conninfo_to_dict(url).get('dbname', '').endswith('_test'):
    raise SystemExit('Test database name must end in _test')
action = sys.argv[1]
now = datetime.now(UTC).replace(microsecond=0)
migrate(url)

if action == 'reset':
    with psycopg.connect(url) as conn:
        conn.execute('DELETE FROM latest_position')
    writer = WriterSession.open(url, 'fintraffic')
    try:
        queue = BootstrapBuffer(writer.epoch)
        feature = {'type':'Feature','id':'987654321',
                   'geometry':{'type':'Point','coordinates':[25,60]},
                   'properties':{'mmsi':'987654321','timestampExternal':int(now.timestamp()*1000)}}
        payload = json.dumps({'time':int(now.timestamp()),'lon':25,'lat':60,'sog':0}).encode()
        queue.push(queue.epoch, 'vessels-v2/987654321/location', payload, now, retained=False)
        state = commit_bootstrap(writer, queue, [feature], now, now)
        for lon in (25, 26):
            payload = json.dumps({'time':int(now.timestamp()),'lon':lon,'lat':60,'sog':0}).encode()
            queue.push(queue.epoch, 'vessels-v2/987654321/location', payload, now, retained=False)
        apply_stream_batch(writer, queue, state, now)
    finally:
        writer.close()
elif action == 'disconnect':
    writer = WriterSession.open(url, 'fintraffic')
    try:
        writer.mark_degraded(now=now, error_code='test_disconnect')
    finally:
        writer.close()
elif action == 'failure':
    writer = WriterSession.open(url, 'fintraffic')
    try:
        try:
            writer.apply_batch([], epoch=writer.epoch,
                               state=SourceStateUpdate('invalid',now,now,now,None), now=now)
            raise AssertionError('expected constraint failure')
        except psycopg.errors.CheckViolation:
            pass
        writer.mark_degraded(now=now, error_code='test_db_failure')
    finally:
        writer.close()
elif action == 'restart':
    writer = WriterSession.open(url, 'fintraffic')
    try:
        queue = BootstrapBuffer(writer.epoch)
        payload = json.dumps({'time':int(now.timestamp()),'lon':25,'lat':60,'sog':0}).encode()
        queue.push(queue.epoch, 'vessels-v2/987654321/location', payload, now, retained=False)
        commit_bootstrap(writer, queue, [], now, now)
    finally:
        writer.close()
elif action == 'expire':
    writer = WriterSession.open(url, 'fintraffic')
    try:
        removed = writer.prune(now=now + timedelta(hours=24, seconds=1))
        if removed < 1:
            raise AssertionError('expected an expired synthetic position')
        writer.mark_degraded(now=now, error_code='test_expired')
    finally:
        writer.close()
else:
    raise SystemExit('Unknown test action')
