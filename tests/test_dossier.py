import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shadow_fleet.api import Settings, create_app

NOW = datetime(2026, 11, 15, tzinfo=UTC)
PATH = '/v1/dossier/fintraffic/123456789'
CITATION = {'title': 'Synthetic vessel register', 'url': 'https://example.org/register',
            'retrieved_on': '2026-11-14', 'license_note': 'Synthetic fixture'}
BINDING = {'source_id':'fintraffic', 'mmsi':'123456789', 'namespace':'training-register',
           'identifier':'demo-1', 'since':'2026-11-01', 'until':'2026-11-20', 'citation':CITATION}
CLAIM = {'namespace':'training-register', 'identifier':'demo-1', 'kind':'registry_record',
         'statement':'Synthetic registry entry', 'published_on':'2026-11-02', 'citation':CITATION}


def client_with(tmp_path, bindings, claims):
    p = tmp_path / 'catalog.json'
    p.write_text(json.dumps({'bindings':bindings,'claims':claims}))
    return TestClient(create_app(Settings('', dossier_path=p), clock=lambda: NOW))


def test_disabled_dossier_and_query_validation():
    client = TestClient(create_app(Settings(''), clock=lambda: NOW))
    assert client.get(PATH).json()['status'] == 'not_configured'
    assert client.get(PATH, params={'on':'bogus'}).status_code == 400
    assert client.get(PATH.replace('123456789','12345')).status_code == 400


def test_dossier_has_provenance_dated_binding_and_claim(tmp_path):
    client = client_with(tmp_path, [BINDING], [CLAIM, {**CLAIM, 'published_on':'2026-11-16'},
                                             {**CLAIM, 'identifier':'demo-2'}])
    data = client.get(PATH).json()
    assert data['status'] == 'linked'
    assert data['bindings'][0]['citation']['url'] == CITATION['url']
    assert [record['statement'] for record in data['external_claims']] == [CLAIM['statement']]
    assert client.get(PATH, params={'on':'2026-11-20'}).json()['status'] == 'no_link'
    assert client.get(PATH.replace('fintraffic','other-provider')).json()['status'] == 'no_link'


def test_overlapping_conflicting_links_do_not_attach_claims(tmp_path):
    client = client_with(tmp_path, [BINDING, {**BINDING, 'identifier':'demo-2'}], [CLAIM])
    data = client.get(PATH).json()
    assert data['status'] == 'ambiguous'
    assert len(data['bindings']) == 2 and data['external_claims'] == []


@pytest.mark.parametrize('body', [b'{}', b'x' * (512 * 1024 + 1),
    json.dumps({'bindings':[{**BINDING,'citation':{**CITATION,'url':'javascript:alert(1)'}}],
                'claims':[]}).encode()], ids=['missing-schema', 'oversize', 'unsafe-url'])
def test_catalog_fails_closed_on_invalid_file(tmp_path: Path, body):
    p = tmp_path / 'bad.json'
    p.write_bytes(body)
    with pytest.raises(ValueError, match='Invalid dossier catalog'):
        create_app(Settings('', dossier_path=p), clock=lambda: NOW)
