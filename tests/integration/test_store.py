"""Integration tests only against an explicitly named disposable test database."""
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest

from shadow_fleet.model import NormalizedPosition
from shadow_fleet.store import SourceStateUpdate, WriterSession, migrate


@pytest.fixture
def dsn():
    value = os.environ.get("SFD_TEST_DATABASE_URL", "")
    if not value or not urlparse(value).path.lstrip("/").endswith("_test"):
        pytest.fail("SFD_TEST_DATABASE_URL must name a disposable database ending in _test")
    import psycopg
    with psycopg.connect(value, autocommit=True) as conn:
        if not conn.info.dbname.endswith("_test"):
            pytest.fail("connected database must end in _test")
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    migrate(value)
    return value


def position(now, *, mmsi="123456789", offset=0, fingerprint=b"a" * 32):
    at = now + timedelta(seconds=offset)
    return NormalizedPosition("fintraffic", mmsi, 25, 60, at, int(at.timestamp()),
                              "second", now, "mqtt", None, None, None, fingerprint, False)


def test_migration_writer_lock_epoch_and_ttl(dsn):
    migrate(dsn)
    now = datetime.now(UTC).replace(microsecond=0)
    state = SourceStateUpdate("live", now, now, now, None)
    writer = WriterSession.open(dsn, "fintraffic")
    try:
        with pytest.raises(RuntimeError, match="writer_already_running"):
            WriterSession.open(dsn, "fintraffic")
        stats = writer.apply_batch([position(now)], epoch=writer.epoch, state=state, now=now)
        assert stats.inserted == 1
        with pytest.raises(RuntimeError, match="stale_epoch"):
            writer.apply_batch([position(now)], epoch=writer.epoch - 1, state=state, now=now)
        assert writer.prune(now=now + timedelta(hours=24)) == 0
        assert writer.prune(now=now + timedelta(hours=24, milliseconds=1)) == 1
    finally:
        writer.close()
    next_writer = WriterSession.open(dsn, "fintraffic")
    assert next_writer.epoch > writer.epoch
    next_writer.close()


def test_batch_rollback_and_conflict(dsn):
    import psycopg
    now = datetime.now(UTC).replace(microsecond=0)
    state = SourceStateUpdate("live", now, now, now, None)
    writer = WriterSession.open(dsn, "fintraffic")
    try:
        a = position(now, mmsi="111111111")
        bad = position(now, mmsi="bad")
        with pytest.raises(psycopg.errors.CheckViolation):
            writer.apply_batch([a, bad], epoch=writer.epoch, state=state, now=now)
        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT count(*) FROM latest_position WHERE mmsi='111111111'").fetchone()[0] == 0
        b = position(now, mmsi="111111111", fingerprint=b"b" * 32)
        result = writer.apply_batch([a, b], epoch=writer.epoch, state=state, now=now)
        assert result.inserted == 1 and result.conflicted == 1
        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT time_conflict FROM latest_position WHERE mmsi='111111111'").fetchone()[0]
    finally:
        writer.close()


def test_migration_checksum_mismatch(dsn, monkeypatch, tmp_path):
    migration = tmp_path / "001_v01.sql"
    migration.write_text("SELECT 1")
    monkeypatch.setattr("shadow_fleet.store.MIGRATIONS", tmp_path)
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        migrate(dsn)


def test_prune_rejects_stale_database_epoch(dsn):
    import psycopg
    writer = WriterSession.open(dsn, "fintraffic")
    try:
        with psycopg.connect(dsn) as conn:
            conn.execute("UPDATE source_state SET epoch=epoch+1 WHERE source_id='fintraffic'")
        with pytest.raises(RuntimeError, match="stale_epoch"):
            writer.prune(now=datetime.now(UTC))
    finally:
        writer.close()


def test_expired_observation_is_not_inserted(dsn):
    import psycopg
    now = datetime.now(UTC).replace(microsecond=0)
    writer = WriterSession.open(dsn, "fintraffic")
    try:
        old = position(now - timedelta(hours=24, seconds=1))
        result = writer.apply_batch([old], epoch=writer.epoch,
                                    state=SourceStateUpdate("live", now, None, None, None), now=now)
        assert result.inserted == 0
        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT count(*) FROM latest_position").fetchone()[0] == 0
    finally:
        writer.close()


def test_database_rejects_invalid_coordinates_and_foreign_source(dsn):
    import psycopg
    now = datetime.now(UTC).replace(microsecond=0)
    sql = """INSERT INTO latest_position
      (source_id,mmsi,geom,provider_time,provider_bucket,time_precision,received_at,transport,
       fingerprint,time_conflict,clock_skew)
      VALUES (%s,'123456789',ST_SetSRID(ST_MakePoint(%s,60),4326),%s,%s,
              'second',%s,'mqtt',%s,false,false)"""
    for source, lon in [("fintraffic", float("nan")), ("fintraffic", 180), ("unknown", 25)]:
        with psycopg.connect(dsn) as conn:
            with pytest.raises(psycopg.IntegrityError):
                conn.execute(sql, (source, lon, now, int(now.timestamp()), now, b"a" * 32))


def test_lost_writer_connection_cannot_commit_and_new_writer_can_start(dsn):
    import psycopg
    now = datetime.now(UTC)
    writer = WriterSession.open(dsn, "fintraffic")
    old_epoch = writer.epoch
    writer.conn.close()
    with pytest.raises(psycopg.Error):
        writer.apply_batch([], epoch=old_epoch,
                           state=SourceStateUpdate("live", now, None, None, None), now=now)
    next_writer = WriterSession.open(dsn, "fintraffic")
    try:
        assert next_writer.epoch > old_epoch
    finally:
        next_writer.close()


def test_replays_and_later_positions_merge_in_database(dsn):
    import psycopg
    now = datetime.now(UTC).replace(microsecond=0)
    state = SourceStateUpdate("live", now, now, now, None)
    writer = WriterSession.open(dsn, "fintraffic")
    try:
        original = position(now)
        writer.apply_batch([original], epoch=writer.epoch, state=state, now=now)
        replay = writer.apply_batch([original], epoch=writer.epoch, state=state, now=now)
        assert replay.ignored == 1
        later = position(now, offset=1, fingerprint=b"b" * 32)
        updated = writer.apply_batch([later], epoch=writer.epoch, state=state, now=now)
        assert updated.updated == 1
        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT provider_time FROM latest_position").fetchone()[0] == later.provider_time
    finally:
        writer.close()


def test_bootstrap_commits_snapshot_and_mqtt_prefix_in_one_transaction(dsn):
    import json
    import psycopg
    from shadow_fleet.collector import BootstrapBuffer, commit_bootstrap

    now = datetime.now(UTC).replace(microsecond=0)
    mqtt = json.dumps({'lon': 26, 'lat': 60, 'time': int(now.timestamp())}).encode()
    feature = {'type': 'Feature', 'id': '123456789',
               'geometry': {'type': 'Point', 'coordinates': [25, 60]},
               'properties': {'mmsi': '123456789', 'timestampExternal': int(now.timestamp() * 1000)}}
    writer = WriterSession.open(dsn, 'fintraffic')
    try:
        queue = BootstrapBuffer(writer.epoch)
        queue.push(writer.epoch, 'vessels-v2/123456789/location', mqtt, now, retained=False)
        commit_bootstrap(writer, queue, [feature], now, now)
        with psycopg.connect(dsn) as conn:
            row = conn.execute("SELECT ST_X(geom), transport, time_conflict FROM latest_position").fetchone()
            state = conn.execute("SELECT sync_state FROM source_state").fetchone()
        assert row == (26, 'mqtt', True)
        assert state == ('live',)
    finally:
        writer.close()


def test_collector_fake_transport_to_database_and_graceful_stop(dsn):
    import json
    import psycopg
    from threading import Event
    from shadow_fleet.collector import Collector
    from shadow_fleet.transport import SnapshotEnvelope

    now = datetime.now(UTC).replace(microsecond=0)
    stop = Event()
    payload = json.dumps({'lon':25, 'lat':60, 'time':int(now.timestamp())}).encode()
    class Store:
        def __init__(self):
            self.session = WriterSession.open(dsn, 'fintraffic')
            self.epoch = self.session.epoch
        def apply_batch(self, positions, *, epoch, state, now, commit_guard=None):
            result = self.session.apply_batch(positions, epoch=epoch, state=state, now=now, commit_guard=commit_guard)
            if state.sync_state == 'live':
                stop.set()
            return result
        def close(self): self.session.close()
    class Transport:
        def __init__(self, queue): self.queue, self.failed = queue, Event()
        def start(self): self.queue.push(self.queue.epoch, 'vessels-v2/123456789/location', payload, now, retained=False)
        def close(self): pass
    Collector(store_factory=Store, transport_factory=Transport,
              fetch=lambda: SnapshotEnvelope([], now), now=lambda: now).run(stop)
    with psycopg.connect(dsn) as conn:
        assert conn.execute('SELECT mmsi FROM latest_position').fetchone() == ('123456789',)
        assert conn.execute('SELECT sync_state FROM source_state').fetchone() == ('degraded',)


def test_writer_enforces_statement_timeout(dsn):
    writer = WriterSession.open(dsn, 'fintraffic')
    try:
        assert writer.conn.execute('SHOW statement_timeout').fetchone()['statement_timeout'] == '5s'
    finally:
        writer.close()


def test_overflow_before_commit_rolls_back_bootstrap(dsn, monkeypatch):
    from shadow_fleet.collector import BootstrapBuffer, BufferOverflow, commit_bootstrap
    import shadow_fleet.store as store_module
    import psycopg
    now = datetime.now(UTC).replace(microsecond=0)
    queue = None
    original = store_module.merge_position
    def fail_during_write(current, incoming):
        queue.fail()
        return original(current, incoming)
    monkeypatch.setattr(store_module, 'merge_position', fail_during_write)
    writer = WriterSession.open(dsn, 'fintraffic')
    queue = BootstrapBuffer(writer.epoch)
    feature = {'type':'Feature', 'id':'123456789',
               'geometry':{'type':'Point','coordinates':[25,60]},
               'properties':{'mmsi':'123456789','timestampExternal':int(now.timestamp()*1000)}}
    try:
        with pytest.raises(BufferOverflow):
            commit_bootstrap(writer, queue, [feature], now, now)
        with psycopg.connect(dsn) as conn:
            assert conn.execute('SELECT count(*) FROM latest_position').fetchone()[0] == 0
            assert conn.execute('SELECT sync_state FROM source_state').fetchone()[0] == 'starting'
    finally:
        writer.close()


def test_writer_enforces_transaction_timeout(dsn):
    writer = WriterSession.open(dsn, 'fintraffic')
    try:
        assert writer.conn.execute('SHOW transaction_timeout').fetchone()['transaction_timeout'] == '15s'
    finally:
        writer.close()


def test_synthetic_restart_failure_and_ttl_recovery(dsn):
    import json
    import psycopg
    from fastapi.testclient import TestClient
    from shadow_fleet.api import Settings, create_app
    from shadow_fleet.collector import BootstrapBuffer, apply_stream_batch, commit_bootstrap

    now = datetime.now(UTC).replace(microsecond=0)
    queue = None
    def payload(lon):
        return json.dumps({'lon':lon, 'lat':60, 'time':int(now.timestamp())}).encode()
    first = WriterSession.open(dsn, 'fintraffic')
    try:
        queue = BootstrapBuffer(first.epoch)
        queue.push(first.epoch, 'vessels-v2/123456789/location', payload(25), now, retained=False)
        state = commit_bootstrap(first, queue, [], now, now)
        queue.push(first.epoch, 'vessels-v2/123456789/location', payload(25), now, retained=False)
        queue.push(first.epoch, 'vessels-v2/123456789/location', payload(26), now, retained=False)
        state = apply_stream_batch(first, queue, state, now)
        with psycopg.connect(dsn) as conn:
            assert conn.execute('SELECT time_conflict FROM latest_position').fetchone()[0] is True
        bad_state = SourceStateUpdate('invalid', now, now, now, None)
        with pytest.raises(psycopg.errors.CheckViolation):
            first.apply_batch([position(now, mmsi='000000002')], epoch=first.epoch,
                              state=bad_state, now=now)
        with psycopg.connect(dsn) as conn:
            assert conn.execute('SELECT count(*) FROM latest_position').fetchone()[0] == 1
    finally:
        first.close()
    next_writer = WriterSession.open(dsn, 'fintraffic')
    try:
        assert next_writer.epoch > first.epoch
        later = now + timedelta(hours=24, milliseconds=1)
        assert next_writer.prune(now=later) == 1
        client = TestClient(create_app(Settings(database_url=dsn), clock=lambda: later))
        response = client.get('/v1/positions/fintraffic/123456789')
        assert response.status_code == 404
    finally:
        next_writer.close()


def test_bbox_query_plan_on_five_thousand_synthetic_rows(dsn):
    import psycopg
    now = datetime.now(UTC).replace(microsecond=0)
    with psycopg.connect(dsn) as conn:
        conn.execute('''INSERT INTO latest_position
          (source_id,mmsi,geom,provider_time,provider_bucket,time_precision,received_at,transport,
           fingerprint,time_conflict,clock_skew)
          SELECT 'fintraffic',lpad(n::text,9,'0'),ST_SetSRID(ST_MakePoint(25,60),4326),
           %s,%s,'second',%s,'mqtt',%s,false,false FROM generate_series(1,5000) n''',
          (now, int(now.timestamp()), now, b'a' * 32))
        plan = conn.execute('EXPLAIN (FORMAT JSON) SELECT mmsi FROM latest_position WHERE geom && ST_MakeEnvelope(20,58,30,62,4326)').fetchone()[0]
        assert plan[0]['Plan']['Node Type']
        assert conn.execute('SELECT count(*) FROM latest_position').fetchone()[0] == 5000


def test_new_writer_sets_starting_heartbeat(dsn):
    import psycopg
    writer = WriterSession.open(dsn, 'fintraffic')
    try:
        with psycopg.connect(dsn) as conn:
            state, heartbeat = conn.execute('SELECT sync_state, heartbeat_at FROM source_state').fetchone()
        assert state == 'starting' and heartbeat is not None
    finally:
        writer.close()


def test_degraded_after_early_failure_preserves_previous_delivery_times(dsn):
    import psycopg
    now = datetime.now(UTC).replace(microsecond=0)
    first = WriterSession.open(dsn, 'fintraffic')
    first.apply_batch([], epoch=first.epoch, state=SourceStateUpdate('live',now,now,now,None), now=now)
    first.close()
    second = WriterSession.open(dsn, 'fintraffic')
    try:
        second.mark_degraded(now=now, error_code='collector_stopped')
        with psycopg.connect(dsn) as conn:
            state, snapshot, mqtt = conn.execute('SELECT sync_state,last_snapshot_at,last_mqtt_at FROM source_state').fetchone()
        assert (state, snapshot, mqtt) == ('degraded', now, now)
    finally:
        second.close()


def test_collector_connect_failure_keeps_previous_delivery_times(dsn):
    import psycopg
    from threading import Event
    from shadow_fleet.collector import Collector
    now = datetime.now(UTC).replace(microsecond=0)
    first = WriterSession.open(dsn, 'fintraffic')
    first.apply_batch([], epoch=first.epoch, state=SourceStateUpdate('live',now,now,now,None), now=now)
    first.close()
    stop = Event()
    class Transport:
        def __init__(self, queue): self.failed = Event()
        def start(self):
            stop.set()
            raise RuntimeError('connection failed')
        def close(self): pass
    Collector(store_factory=lambda: WriterSession.open(dsn, 'fintraffic'),
              transport_factory=Transport, now=lambda: now).run(stop)
    with psycopg.connect(dsn) as conn:
        assert conn.execute('SELECT sync_state,last_snapshot_at,last_mqtt_at FROM source_state').fetchone() == ('degraded', now, now)


def test_history_is_opt_in_and_reconciles_each_second(dsn):
    from dataclasses import replace

    import psycopg

    now = datetime.now(UTC).replace(microsecond=0)
    state = SourceStateUpdate('live', now, now, now, None)
    writer = WriterSession.open(dsn, 'fintraffic')
    try:
        writer.apply_batch([position(now, offset=-2)], epoch=writer.epoch, state=state, now=now)
        with psycopg.connect(dsn) as conn:
            assert conn.execute('SELECT count(*) FROM position_history').fetchone()[0] == 0
    finally:
        writer.close()
    writer = WriterSession.open(dsn, 'fintraffic', record_history=True)
    try:
        older = position(now, offset=-1)
        rest = replace(older, provider_time=older.provider_time + timedelta(milliseconds=500),
                       time_precision='millisecond', transport='rest', lon=26, fingerprint=b'b' * 32)
        for batch in ([position(now), rest], [older], [rest, older, position(now)]):
            writer.apply_batch(batch, epoch=writer.epoch, state=state, now=now)
        with psycopg.connect(dsn) as conn:
            assert conn.execute('SELECT transport, ST_X(geom), time_conflict FROM position_history '
                                'ORDER BY provider_bucket').fetchall() == [('mqtt', 25, True), ('mqtt', 25, False)]
            assert conn.execute('SELECT provider_time FROM latest_position').fetchone()[0] == now
    finally:
        writer.close()


def test_history_rolls_back_and_expires_separately(dsn):
    import psycopg

    now = datetime.now(UTC).replace(microsecond=0)
    writer = WriterSession.open(dsn, 'fintraffic', record_history=True)
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            writer.apply_batch([position(now)], epoch=writer.epoch,
                               state=SourceStateUpdate('invalid', now, now, now, None), now=now)
        with psycopg.connect(dsn) as conn:
            assert conn.execute('SELECT count(*) FROM position_history').fetchone()[0] == 0
        writer.apply_batch([position(now)], epoch=writer.epoch,
                           state=SourceStateUpdate('live', now, now, now, None), now=now)
        assert writer.prune(now=now + timedelta(days=1, seconds=1)) == 1
        writer.prune_history(now=now + timedelta(days=7))
        with psycopg.connect(dsn) as conn:
            assert conn.execute('SELECT count(*) FROM position_history').fetchone()[0] == 1
        writer.prune_history(now=now + timedelta(days=7, seconds=1))
        with psycopg.connect(dsn) as conn:
            assert conn.execute('SELECT count(*) FROM position_history').fetchone()[0] == 0
    finally:
        writer.close()
