"""WEB-5 HTTP boundary accepts only exact-plan capabilities."""

import json
import logging

from fastapi.testclient import TestClient

from tests.auth_support import authenticated_app as create_app
from netbox_sync.api.settings import ApiSettings


HEADERS = {'host': 'localhost:8000', 'origin': 'http://localhost:8000',
           'x-netbox-sync-csrf': 'same-origin', 'content-type': 'application/json'}


class Discovery:
    def plan(self, instance):
        return {'source_instance': instance, 'source_id': 'internal', 'source_type': 'proxmox',
                'source_fingerprint': 'a', 'target_fingerprint': 'b',
                'provider_fingerprint': 'c', 'netbox_fingerprint': 'd', 'schema_version': 1,
                'planner_version': 'web-5a-1', 'items': [], 'apply_allowed': True,
                'digest': 'a' * 64}

    def discover(self, _instance):
        raise AssertionError('discovery endpoint not used')


class Apply:
    def __init__(self):
        self.calls = []

    def prepare(self, instance, digest):
        self.calls.append(('prepare', instance, digest))
        return {'confirmation_token': 'b' * 64, 'expires_in_seconds': 300}

    def apply(self, instance, token):
        self.calls.append(('apply', instance, token))
        return {'status': 'SUCCEEDED', 'plan_digest': 'a' * 64,
                'run_id': '11111111-1111-4111-8111-111111111111'}


def test_plan_prepare_apply_flow_and_payload_boundaries(caplog):
    worker = Apply()
    api = TestClient(create_app(ApiSettings(allowed_write_hosts=('localhost:8000',)),
                                discovery_client=Discovery(), apply_client=worker))
    with caplog.at_level(logging.INFO, logger='netbox_sync.api'):
        planned = api.post('/api/v1/sources/pve-test/sync-plan', headers=HEADERS, json={})
        assert planned.status_code == 200
        assert 'source_id' not in planned.json()
        prepared = api.post('/api/v1/sources/pve-test/sync-confirmations', headers=HEADERS,
                            json={'plan_digest': 'a' * 64, 'confirmed': True})
        assert prepared.status_code == 200
        applied = api.post('/api/v1/sources/pve-test/sync', headers=HEADERS,
                           json={'confirmation_token': 'b' * 64})
    assert applied.status_code == 200
    assert applied.json()['run_id'] == '11111111-1111-4111-8111-111111111111'
    assert worker.calls == [('prepare', 'pve-test', 'a' * 64),
                            ('apply', 'pve-test', 'b' * 64)]
    records = [json.loads(record.message) for record in caplog.records
               if record.name == 'netbox_sync.api']
    assert records[-1]['run_id'] == applied.json()['run_id']


def test_client_cannot_submit_operations_or_skip_same_origin_boundary():
    worker = Apply()
    api = TestClient(create_app(ApiSettings(allowed_write_hosts=('localhost:8000',)),
                                discovery_client=Discovery(), apply_client=worker))
    assert api.post('/api/v1/sources/pve-test/sync-plan', headers=HEADERS,
                    json={'operations': ['delete']}).status_code == 422
    response = api.post('/api/v1/sources/pve-test/sync', headers=HEADERS,
                        json={'confirmation_token': 'b' * 64, 'operations': ['delete']})
    assert response.status_code == 422
    assert worker.calls == []
    assert api.post('/api/v1/sources/pve-test/sync',
                    json={'confirmation_token': 'b' * 64}).status_code == 403
