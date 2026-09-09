"""WEB-4 transport and DTO boundaries without external services."""

import json

import pytest
from fastapi.testclient import TestClient

from tests.auth_support import authenticated_app as create_app
from netbox_sync.api.discovery_client import DiscoveryRequestError
from netbox_sync.api.settings import ApiSettings


SECRET = 'DISCOVERY_SECRET_SENTINEL'
HEADERS = {'host': 'localhost:8000', 'origin': 'http://localhost:8000',
           'x-netbox-sync-csrf': 'same-origin', 'content-type': 'application/json'}


def result(**changes):
    value = {'source_instance': 'pve-test', 'source_type': 'proxmox', 'site_slug': 'test',
             'cluster_name': 'Test', 'items': [{'object_kind': 'qemu', 'name': 'vm-1',
             'external_id': '1', 'classification': 'WOULD_CREATE',
             'reason_code': 'NO_IDENTITY_MATCH', 'reason': 'No identity match.',
             'future_action': 'create', 'matched_object_id': None, 'matched_object_name': None}]}
    value.update(changes)
    return value


class FakeDiscovery:
    def __init__(self, value=None, error=None):
        self.value, self.error, self.calls = value or result(), error, []

    def discover(self, instance):
        self.calls.append(instance)
        if self.error:
            raise DiscoveryRequestError(self.error)
        return self.value


def client(discovery):
    settings = ApiSettings(allowed_write_hosts=('localhost:8000',))
    return TestClient(create_app(settings, discovery_client=discovery))


def test_protected_discovery_returns_only_allowlisted_dto(caplog):
    discovery = FakeDiscovery()
    with client(discovery) as api:
        response = api.post('/api/v1/sources/pve-test/discovery', headers=HEADERS, json={})
    assert response.status_code == 200
    assert response.json() == result()
    assert discovery.calls == ['pve-test']
    assert SECRET not in response.text + caplog.text


def test_discovery_requires_same_origin_control_boundary():
    discovery = FakeDiscovery()
    with client(discovery) as api:
        response = api.post('/api/v1/sources/pve-test/discovery', json={})
    assert response.status_code == 403
    assert discovery.calls == []


@pytest.mark.parametrize(('code', 'status'), [
    ('SOURCE_NOT_FOUND', 404), ('SOURCE_DISABLED', 409), ('DISCOVERY_TIMEOUT', 504),
    ('CREDENTIAL_UNAVAILABLE', 503), ('DISCOVERY_UNAVAILABLE', 503), ('DISCOVERY_FAILED', 502),
])
def test_stable_discovery_errors(code, status):
    with client(FakeDiscovery(error=code)) as api:
        response = api.post('/api/v1/sources/pve-test/discovery', headers=HEADERS, json={})
    assert response.status_code == status
    assert response.json()['error']['code'] == code


@pytest.mark.parametrize('change', [
    {'source_instance': SECRET}, {'items': [{'credentials': SECRET}]},
    {'items': [{**result()['items'][0], 'classification': ['WOULD_CREATE']}]},
])
def test_malformed_or_secret_bearing_worker_response_is_rejected(change):
    with client(FakeDiscovery(result(**change))) as api:
        response = api.post('/api/v1/sources/pve-test/discovery', headers=HEADERS, json={})
    assert response.status_code in (500, 502)
    assert SECRET not in response.text


def test_request_payload_cannot_select_path_host_or_provider():
    discovery = FakeDiscovery()
    payload = {'secret_path': '/etc/shadow', 'address': '127.0.0.1', 'provider': 'module'}
    with client(discovery) as api:
        response = api.post('/api/v1/sources/pve-test/discovery', headers=HEADERS,
                            content=json.dumps(payload))
    assert response.status_code == 200
    assert discovery.calls == ['pve-test']
