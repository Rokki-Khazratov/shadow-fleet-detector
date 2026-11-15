"""Run acceptance without the working database, .env, or a live data provider."""
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from threading import Thread

import psycopg
import uvicorn
from psycopg import sql

from shadow_fleet.api import Settings, create_app

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'postgis/postgis:17-3.5@sha256:01a6a70e41e6c4467c8f55f6063555ed72db2d6662cd0d571040d42eadaeb6f6'


def run(command, *, cwd=ROOT, env=None):
    subprocess.run(command, cwd=cwd, env=env, check=True)


def wait_for(check, seconds=30):
    deadline = time.monotonic() + seconds
    while not check():
        if time.monotonic() >= deadline:
            raise RuntimeError('Local acceptance service did not become ready')
        time.sleep(0.2)


def database_ready(dsn):
    try:
        with psycopg.connect(dsn, connect_timeout=2) as conn:
            return conn.execute('SELECT 1').fetchone() == (1,)
    except psycopg.OperationalError:
        return False


def readonly_url(admin_url, authority):
    password = secrets.token_hex(24)
    with psycopg.connect(admin_url) as conn:
        conn.execute(sql.SQL('CREATE ROLE sfd_browser LOGIN PASSWORD {}').format(sql.Literal(password)))
        conn.execute('GRANT USAGE ON SCHEMA public TO sfd_browser')
        conn.execute('GRANT SELECT ON source, source_state, latest_position, position_history TO sfd_browser')
    return f'postgresql://sfd_browser:{password}@{authority}'


def browser_acceptance(reader_url, env):
    app = create_app(Settings(reader_url, ROOT / 'tests/fixtures/dossier-synthetic.json'))
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))
    with socket.socket() as api, socket.socket() as web:
        api.bind(('127.0.0.1', 0))
        web.bind(('127.0.0.1', 0))
        browser_env = {**env, 'SFD_API_PROXY': f'http://127.0.0.1:{api.getsockname()[1]}',
                       'SFD_TEST_WEB_PORT': str(web.getsockname()[1]), 'SFD_REAL_API_TEST': '1',
                       'SFD_ACCEPT_DOSSIER': '1'}
        thread = Thread(target=server.run, kwargs={'sockets':[api]}, daemon=True)
        thread.start()
        try:
            wait_for(lambda: server.started)
            web.close()
            run(['npm', 'run', 'test:e2e', '--', '--workers=1'], cwd=ROOT / 'web', env=browser_env)
        finally:
            server.should_exit = True
            thread.join(timeout=10)


def main():
    name = f'sfd-release-{secrets.token_hex(5)}'
    password = secrets.token_hex(24)
    env = os.environ.copy()
    for key in ('SFD_DATABASE_URL', 'SFD_API_DATABASE_URL', 'SFD_DOSSIER_CATALOG', 'POSTGRES_PASSWORD'):
        env.pop(key, None)
    print('Starting disposable PostGIS; working database will not be contacted.', flush=True)
    started = False
    try:
        subprocess.run(['docker', 'run', '-d', '--rm', '--name', name, '--platform', 'linux/amd64',
                        '-e', 'POSTGRES_USER=sfd_test', '-e', 'POSTGRES_PASSWORD',
                        '-e', 'POSTGRES_DB=sfd_release_test', '-p', '127.0.0.1::5432', IMAGE],
                       env={**env, 'POSTGRES_PASSWORD':password}, check=True, stdout=subprocess.DEVNULL)
        started = True
        hostport = subprocess.check_output(['docker', 'port', name, '5432/tcp'], text=True).strip()
        host, _, port = hostport.partition(':')
        if host != '127.0.0.1' or not port.isdigit():
            raise RuntimeError('Unexpected test DB binding')
        authority = f'{hostport}/sfd_release_test'
        dsn = f'postgresql://sfd_test:{password}@{authority}'
        env['SFD_TEST_DATABASE_URL'] = dsn
        wait_for(lambda: database_ready(dsn))
        run([sys.executable, '-m', 'pytest', '-q'], env=env)
        run([sys.executable, '-m', 'ruff', 'check', 'src', 'tests', 'benchmarks', 'scripts'], env=env)
        run([sys.executable, 'tests/integration/seed_browser.py'], env=env)
        browser_acceptance(readonly_url(dsn, authority), env)
        run(['npm', 'run', 'typecheck'], cwd=ROOT / 'web', env=env)
        run(['npm', 'run', 'build'], cwd=ROOT / 'web', env=env)
    finally:
        if started:
            subprocess.run(['docker', 'stop', name], check=True, stdout=subprocess.DEVNULL, timeout=30)
    print('Local acceptance passed; disposable database removed.', flush=True)


if __name__ == '__main__':
    main()
