"""HTTP regressions for registration refusals before any durable writes."""
from contextlib import nullcontext
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import netbox_sync.api.app as api
import netbox_sync.local_control as control
import netbox_sync.registration_jobs as registration_jobs
from netbox_sync.api.auth import COOKIE
from netbox_sync.api.settings import ApiSettings
from tests.test_directory_auth import configured
from tests.test_operator_registration import HEADERS


CASES = [
    ('closed', 'HOST_SOURCE_CLOSED'),
    ('wrong-source', 'HOST_REGISTRATION_INVALID'),
    ('invalid-closed', 'HOST_REGISTRATION_INVALID'),
    ('upgrade', 'HOST_INTEGRATION_UPGRADE_REQUIRED'),
    ('unavailable', 'HOST_INTEGRATION_UNAVAILABLE'),
    ('foreign-namespace', 'HOST_REGISTRATION_INVALID'),
]


@pytest.mark.parametrize('staged', [False, True], ids=['direct', 'durable'])
@pytest.mark.parametrize('reason,code', CASES)
def test_registration_refusal_is_domain_conflict(monkeypatch, staged, reason, code):
    check_refusal(monkeypatch, staged, reason, code)


def test_changed_durable_intent_is_domain_conflict(monkeypatch):
    check_refusal(monkeypatch, True, 'changed-intent', 'HOST_REGISTRATION_INTENT_CHANGED')


def check_refusal(monkeypatch, staged, reason, code):
    policy, _, session = configured('operator')
    token = 'refusal-regression-token-12345678'
    policy.call(dict(action='receipt.issue', session=session, receipt=token,
                     provider='proxmox', destination='source.test', revision=0))
    actions = []

    class Auth:
        def call(self, action, **payload):
            actions.append(action)
            return policy.call(dict(action=action, **payload))

    body = dict(onboarding_token=token, source_type='proxmox', source_instance='new-source',
                name='New source', address='source.test', verify_ssl=True,
                sync_interval_seconds=600, site_slug='test', cluster_name='Test',
                platform_slug='platform', device_role_slug='host', device_type_slug='server',
                cluster_type_slug='cluster', confirm_sync_disabled=True, registration_id=str(uuid4()))
    onboarding = Mock()
    onboarding.registration_admission.side_effect = nullcontext
    onboarding.registration_outcome.return_value = {'identity_status': 'NOT_FOUND'}
    monkeypatch.setattr(api, 'SourceOnboardingService', lambda *args, **kwargs: onboarding)
    jobs = Mock()
    jobs.guard.side_effect = lambda *args: nullcontext()
    jobs.get.return_value = None
    if reason == 'changed-intent':
        jobs.get.return_value = {'payload': {'request': {**body, 'name': 'Original name'}}}
    continuation = Mock()
    monkeypatch.setattr(registration_jobs, 'RegistrationJobs', lambda *args: jobs)
    monkeypatch.setattr(registration_jobs, 'RegistrationContinuation', lambda *args: continuation)

    def namespace_check(path, payload, **kwargs):
        assert payload['action'] == 'namespace-check'
        if reason in ('upgrade', 'unavailable'):
            raise control.ControlError('RETIREMENT_GUARD_CHANGED' if reason == 'upgrade' else 'CONTROL_UNAVAILABLE')
        return {'result': {'source_instance': 'other-source' if reason == 'wrong-source' else 'new-source',
                           'closed': 'false' if reason == 'invalid-closed' else reason == 'closed'}}

    monkeypatch.setattr(control, 'request', namespace_check)
    settings = ApiSettings(bootstrap_socket='', registration_dsn='fixture' if staged else '',
                           source_namespace='a' * 32 if reason == 'foreign-namespace' else '')
    app = api.create_app(settings=settings, auth_client=Auth())
    # No lifespan: exercise the HTTP admission boundary without starting a worker.
    http = TestClient(app, base_url='https://localhost:8000')
    try:
        http.cookies.set(COOKIE, session)
        response = http.post('/api/v1/sources', headers=HEADERS, json=body)
    finally:
        http.close()
    assert response.status_code == 409, response.text
    error = response.json()['error']
    assert error['code'] == code
    assert error['request_id'] and error['message']
    assert token not in response.text
    assert 'NameError' not in response.text
    assert 'receipt.consume' not in actions
    onboarding.reserve_provider_identity.assert_not_called()
    onboarding.register.assert_not_called()
    onboarding._pending.consume.assert_not_called()
    jobs.begin.assert_not_called()
    jobs.stage.assert_not_called()
    continuation.run.assert_not_called()
