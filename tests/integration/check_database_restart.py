"""Manual acceptance: physically stop and restart a dedicated disposable Docker DB."""
import subprocess
import time
from datetime import UTC, datetime

import psycopg
from fastapi.testclient import TestClient

from shadow_fleet.api import Settings, create_app
from shadow_fleet.fintraffic import normalize_mqtt
from shadow_fleet.store import SourceStateUpdate, WriterSession, migrate

CONTAINER = 'sfd-phase1-20261115'
DSN = 'postgresql://sfd_test:sfd_test@127.0.0.1:55449/sfd_phase1_test'
URL = '/v1/positions/fintraffic/987654320'


def docker(action):
    subprocess.run(['docker', action, CONTAINER], check=True, timeout=30, stdout=subprocess.DEVNULL)


def run():
    # Refuse even a similarly named container mapped to another target.
    port = subprocess.check_output(['docker', 'port', CONTAINER, '5432/tcp'], text=True).strip()
    if port != '127.0.0.1:55449':
        raise RuntimeError('unexpected test container port')
    migrate(DSN)
    now = datetime.now(UTC).replace(microsecond=0)
    p = normalize_mqtt('vessels-v2/987654320/location', {'time': int(now.timestamp()),
                       'lon':25, 'lat':60, 'sog':0}, received_at=now)
    writer = WriterSession.open(DSN, 'fintraffic')
    state = SourceStateUpdate('live', now, now, now, None)
    try:
        writer.apply_batch([p], epoch=writer.epoch, state=state, now=now)
        with TestClient(create_app(Settings(DSN))) as client:
            assert client.get(URL).status_code == 200
            docker('stop')
            try:
                response = client.get(URL)
                assert response.status_code == 503
                assert response.json()['error']['code'] == 'database_unavailable'
                try:
                    writer.apply_batch([p], epoch=writer.epoch, state=state, now=now)
                except psycopg.OperationalError:
                    pass
                else:
                    raise AssertionError('old connection unexpectedly survived')
            finally:
                docker('start')
            for _ in range(30):
                response = client.get(URL)
                if response.status_code != 503:
                    break
                time.sleep(0.2)
            assert response.status_code == 200 and response.json()['item']['lon'] == 25
            next_writer = WriterSession.open(DSN, 'fintraffic')
            try:
                assert next_writer.epoch > writer.epoch
                assert client.get(URL).json()['source']['sync_state'] == 'starting'
            finally:
                next_writer.close()
    finally:
        writer.close()
    print('PASS: storage survived physical shutdown, API 503 → 200, writer epoch advanced')


if __name__ == '__main__':
    run()
