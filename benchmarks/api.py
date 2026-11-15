"""Destructive benchmark: use only with an isolated, disposable *_test database."""
import os
import platform
import statistics
import time
from datetime import UTC, datetime

import psycopg
from fastapi.testclient import TestClient

from shadow_fleet.api import Settings, create_app

dsn = os.environ['SFD_TEST_DATABASE_URL']
with psycopg.connect(dsn) as conn:
    if not conn.info.dbname.endswith('_test'):
        raise SystemExit('Database name must end with _test')
    conn.execute('DELETE FROM latest_position')
    now = datetime.now(UTC).replace(microsecond=0)
    conn.execute('''INSERT INTO latest_position
      (source_id,mmsi,geom,provider_time,provider_bucket,time_precision,received_at,transport,
       fingerprint,time_conflict,clock_skew)
      SELECT 'fintraffic',lpad(n::text,9,'0'),ST_SetSRID(ST_MakePoint(25,60),4326),
       %s,%s,'second',%s,'mqtt',%s,false,false FROM generate_series(1,5000) n''',
       (now, int(now.timestamp()), now, b'a'*32))
client = TestClient(create_app(Settings(dsn)))
params = {'west': -180, 'south': -90, 'east': 180, 'north': 90}
for _ in range(5):
    assert client.get('/v1/positions', params=params).status_code == 200
samples = []
for _ in range(100):
    start = time.perf_counter()
    result = client.get('/v1/positions', params=params)
    assert result.status_code == 200 and result.json()['truncated']
    samples.append((time.perf_counter() - start) * 1000)
print('platform:', platform.platform(), platform.machine())
print('samples:', len(samples), 'rows: 5000, returned: 2000, bytes:', len(result.content))
print('p95 ms:', round(sorted(samples)[94], 2), 'median ms:', round(statistics.median(samples), 2))
