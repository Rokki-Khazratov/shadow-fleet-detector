"""API tests with synthetic data in an explicitly disposable PostGIS database."""
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import psycopg
import pytest
from fastapi.testclient import TestClient

from shadow_fleet.api import Settings, create_app
from shadow_fleet.store import migrate

NOW = datetime(2026, 11, 14, 18, 0, tzinfo=UTC)
WORLD = {"west": -180, "south": -90, "east": 180, "north": 90}


@pytest.fixture
def db():
    dsn = os.environ.get("SFD_TEST_DATABASE_URL", "")
    if not dsn or not urlparse(dsn).path.lstrip("/").endswith("_test"):
        pytest.fail("SFD_TEST_DATABASE_URL must name a disposable database ending in _test")
    with psycopg.connect(dsn, autocommit=True) as conn:
        if not conn.info.dbname.endswith("_test"):
            pytest.fail("connected database must end in _test")
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    migrate(dsn)
    return dsn


@pytest.fixture
def client(db):
    return TestClient(create_app(Settings(database_url=db), clock=lambda: NOW))


def insert(conn, mmsi, lon, at=NOW, lat=60):
    conn.execute("""INSERT INTO latest_position
    (source_id,mmsi,geom,provider_time,provider_bucket,time_precision,received_at,transport,
    fingerprint,time_conflict,clock_skew,sog_kn) VALUES
    ('fintraffic',%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,%s,'second',%s,'mqtt',%s,false,false,0)
    """, (mmsi, lon, lat, at, int(at.timestamp()), NOW, b'a' * 32))


def test_empty_and_validation(client):
    response = client.get('/v1/positions', params=WORLD)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['items'] == []
    assert response.json()['source']['sync_state'] == 'starting'
    for params in ({}, dict(WORLD, west='NaN'), dict(WORLD, south=90),
                   dict(WORLD, west=180, east=-180), dict(WORLD, west=0, east=0)):
        response = client.get('/v1/positions', params=params)
        assert response.status_code == 400
        assert response.json()['error']['code'] == 'invalid_bbox'
    assert client.get('/v1/positions/fintraffic/not-an-mmsi').json()['error']['code'] == 'invalid_mmsi'
    assert client.get('/v1/positions/fintraffic/000000001').status_code == 404


def test_seam_ttl_detail_and_health(db, client):
    with psycopg.connect(db) as conn:
        insert(conn, '000000001', -180)
        insert(conn, '000000002', 179)
        insert(conn, '000000003', -179)
        insert(conn, '000000004', 25, NOW - timedelta(hours=24, seconds=1))
        conn.execute("UPDATE source_state SET sync_state='live', heartbeat_at=%s, last_mqtt_at=%s",
                     (NOW - timedelta(seconds=16), NOW))
    response = client.get('/v1/positions', params=dict(WORLD, west=170, east=180))
    assert {p['mmsi'] for p in response.json()['items']} == {'000000001', '000000002'}
    response = client.get('/v1/positions', params=dict(WORLD, west=170, east=-170))
    assert {p['mmsi'] for p in response.json()['items']} == {'000000001', '000000002', '000000003'}
    assert response.json()['source']['sync_state'] == 'degraded'
    detail = client.get('/v1/positions/fintraffic/000000001').json()
    assert detail['item']['sog_kn'] == 0
    assert 'fingerprint' not in detail['item']
    assert client.get('/v1/positions/fintraffic/000000004').status_code == 404


def test_database_outage_is_503():
    client = TestClient(create_app(Settings(database_url='postgresql://x:x@127.0.0.1:1/x'), clock=lambda: NOW))
    response = client.get('/v1/positions', params=WORLD)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'database_unavailable'
    assert response.headers['cache-control'] == 'no-store'


def test_order_limit_and_freshness_boundaries(db, client):
    with psycopg.connect(db) as conn:
        conn.execute("""INSERT INTO latest_position
          (source_id,mmsi,geom,provider_time,provider_bucket,time_precision,received_at,transport,
           fingerprint,time_conflict,clock_skew)
          SELECT 'fintraffic', lpad(n::text,9,'0'), ST_SetSRID(ST_MakePoint(25,60),4326),
            %s, %s, 'second', %s, 'mqtt', %s, false, false
          FROM generate_series(1,2001) AS n""", (NOW, int(NOW.timestamp()), NOW, b'a' * 32))
    data = client.get('/v1/positions', params=WORLD).json()
    assert data['truncated'] is True and len(data['items']) == 2000
    assert data['items'][0]['mmsi'] == '000000001'
    assert data['items'][-1]['mmsi'] == '000002000'


def test_missing_state_fresh_stale_and_clock_skew(db, client):
    with psycopg.connect(db) as conn:
        insert(conn, '000000001', 25, NOW - timedelta(seconds=300))
        insert(conn, '000000002', 26, NOW - timedelta(seconds=301))
        insert(conn, '000000003', 27, NOW + timedelta(seconds=30))
        conn.execute("UPDATE latest_position SET clock_skew=true WHERE mmsi='000000003'")
        conn.execute("DELETE FROM source_state WHERE source_id='fintraffic'")
    data = client.get('/v1/positions', params=WORLD).json()
    by_id = {p['mmsi']: p for p in data['items']}
    assert data['source']['sync_state'] == 'starting'
    assert data['source']['last_mqtt_at'] is None
    assert by_id['000000001']['stale'] is False
    assert by_id['000000002']['stale'] is True
    assert by_id['000000003']['age_seconds'] == 0
    assert by_id['000000003']['clock_skew'] is True


def test_openapi_exposes_position_response_schema(client):
    spec = client.get('/openapi.json').json()
    schema = spec['paths']['/v1/positions']['get']['responses']['200']['content']['application/json']['schema']
    assert schema.get('$ref', '').endswith('/PositionPage')


def test_api_with_select_only_database_role(db):
    from uuid import uuid4
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    role = 'sfd_reader_' + uuid4().hex
    with psycopg.connect(db, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'test-only-password'").format(sql.Identifier(role)))
        try:
            admin.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
            admin.execute(sql.SQL('GRANT SELECT ON source, source_state, latest_position, position_history TO {}').format(sql.Identifier(role)))
            reader_dsn = make_conninfo(db, user=role, password='test-only-password')
            reader = TestClient(create_app(Settings(database_url=reader_dsn), clock=lambda: NOW))
            assert reader.get('/v1/positions', params=WORLD).status_code == 200
            assert reader.get('/v1/history/fintraffic/000000001', params={
                'from': (NOW - timedelta(hours=1)).isoformat(), 'to': NOW.isoformat(),
            }).status_code == 200
            for table in ('latest_position', 'position_history'):
                with psycopg.connect(reader_dsn) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
        finally:
            admin.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_positions_and_source_use_same_database_snapshot(db, client, monkeypatch):
    import shadow_fleet.api as api
    original = api._source

    def write_after_source_read(conn, source_id, as_of):
        source = original(conn, source_id, as_of)
        with psycopg.connect(db) as writer:
            insert(writer, '000000001', 25)
        return source

    monkeypatch.setattr(api, '_source', write_after_source_read)
    response = client.get('/v1/positions', params=WORLD)
    assert response.status_code == 200
    assert response.json()['items'] == []
    with psycopg.connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM latest_position').fetchone()[0] == 1


def test_stale_syncing_heartbeat_is_degraded(db, client):
    with psycopg.connect(db) as conn:
        conn.execute("UPDATE source_state SET sync_state='syncing', heartbeat_at=%s", (NOW - timedelta(seconds=16),))
    data = client.get('/v1/positions', params=WORLD).json()
    assert data['source']['sync_state'] == 'degraded'


def test_history_returns_bounded_ordered_observations_with_attribution(db, client):
    with psycopg.connect(db) as conn:
        for offset in range(3, -1, -1):
            at = NOW - timedelta(seconds=offset)
            conn.execute('''INSERT INTO position_history
                (source_id,mmsi,geom,provider_time,provider_bucket,time_precision,received_at,transport,
                fingerprint,time_conflict,clock_skew)
                VALUES ('fintraffic','000000001',ST_SetSRID(ST_MakePoint(25,60),4326),
                        %s,%s,'second',%s,'mqtt',%s,false,false)''', (at, int(at.timestamp()), NOW, b'a' * 32))
    response = client.get('/v1/history/fintraffic/000000001', params={
        'from': (NOW - timedelta(seconds=3)).isoformat(), 'to': NOW.isoformat(), 'limit': 2,
    })
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    data = response.json()
    assert data['source']['id'] == 'fintraffic'
    assert 'CC BY 4.0' in data['source']['attribution']
    assert data['mmsi'] == '000000001' and data['truncated'] is True
    assert [datetime.fromisoformat(point['provider_time']) for point in data['items']] == [
        NOW - timedelta(seconds=3), NOW - timedelta(seconds=2)]
    assert not {'fingerprint', 'age_seconds', 'stale'} & data['items'][0].keys()
    unclipped = client.get('/v1/history/fintraffic/000000001', params={
        'from': (NOW - timedelta(seconds=3)).isoformat(), 'to': NOW.isoformat(),
    }).json()
    assert len(unclipped['items']) == 3 and unclipped['truncated'] is False


def test_history_validates_window_and_distinguishes_empty_from_unknown_source(client):
    endpoint = '/v1/history/fintraffic/000000001'
    window = {'from': (NOW - timedelta(hours=1)).isoformat(), 'to': NOW.isoformat()}
    for params in ({}, {**window, 'limit': 1001}, {**window, 'limit': 'nan'},
                   {**window, 'from': '2026-11-14T17:00:00'},
                   {**window, 'from': NOW.isoformat()},
                   {**window, 'from': (NOW - timedelta(days=8)).isoformat()}):
        assert client.get(endpoint, params=params).status_code == 400
    assert client.get(endpoint.replace('fintraffic', 'unknown'), params=window).status_code == 404
    assert client.get(endpoint.replace('000000001', 'bad'), params=window).status_code == 400
    assert client.get(endpoint, params=window).json()['items'] == []
