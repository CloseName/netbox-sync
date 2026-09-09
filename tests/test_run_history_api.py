"""Read-only Run History API uses explicit safe DTOs and bounded filters."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from tests.auth_support import authenticated_app as create_app
from netbox_sync.api.settings import ApiSettings
from netbox_sync.application.runs import RunHistoryService
from netbox_sync.run_history import ActionCounts, RunStatus, RunTrigger, SyncRun


RUN = SyncRun(UUID('11111111-1111-4111-8111-111111111111'), 'pve-test', 'proxmox',
              RunTrigger.MANUAL, datetime(2026, 1, 1, tzinfo=timezone.utc),
              datetime(2026, 1, 1, tzinfo=timezone.utc), 0, RunStatus.LOCKED,
              'a' * 64, 'web-5a-1', ActionCounts(create=1), 'APPLY_LOCKED',
              'Another synchronization is already running.', 'web/manual')


class Reader:
    def __init__(self):
        self.filters = None

    def list_runs(self, **filters):
        self.filters = filters
        return (RUN,)

    def get_run(self, run_id):
        return RUN if str(run_id) == str(RUN.run_id) else None


def client(reader=None):
    return TestClient(create_app(ApiSettings(), run_service=RunHistoryService(reader or Reader())))


def test_run_list_detail_and_safe_dto_allowlist():
    reader = Reader()
    with client(reader) as api:
        response = api.get('/api/v1/runs?source_instance=pve-test&source_type=proxmox&trigger=manual&status=LOCKED&limit=20')
        detail = api.get('/api/v1/runs/' + str(RUN.run_id))
    assert response.status_code == detail.status_code == 200
    assert reader.filters['limit'] == 20
    assert response.json()['runs'][0] == detail.json()
    serialized = str(detail.json()).casefold()
    assert not any(value in serialized for value in ('password', 'token_secret', 'dsn', 'traceback'))


def test_run_detail_404_and_invalid_filters():
    with client() as api:
        missing = api.get('/api/v1/runs/22222222-2222-4222-8222-222222222222')
        invalid_limit = api.get('/api/v1/runs?limit=201')
        invalid_status = api.get('/api/v1/runs?status=UNKNOWN')
        invalid_cursor = api.get('/api/v1/runs?cursor=not-a-uuid')
        invalid_source = api.get('/api/v1/runs?source_instance=unsafe/value')
    assert missing.status_code == 404
    assert missing.json()['error']['code'] == 'RUN_NOT_FOUND'
    assert invalid_limit.status_code == invalid_status.status_code == 422
    assert invalid_cursor.status_code == invalid_source.status_code == 422
    assert invalid_status.json()['error']['code'] == 'RUN_FILTER_INVALID'
    assert invalid_limit.json()['error']['code'] == 'RUN_FILTER_INVALID'


def test_run_history_unavailable_is_safe_and_hides_database_exception():
    class Unavailable:
        def list_runs(self, **_filters):
            raise RuntimeError('FAKE_DATABASE_DETAIL_MUST_NOT_APPEAR')

        def get_run(self, _run_id):
            raise RuntimeError('raw database exception')

    with client(Unavailable()) as api:
        listed = api.get('/api/v1/runs')
        detailed = api.get('/api/v1/runs/' + str(RUN.run_id))
    assert listed.status_code == detailed.status_code == 503
    assert listed.json()['error']['code'] == 'RUN_HISTORY_UNAVAILABLE'
    assert not any(secret in str((listed.json(), detailed.json())) for secret in (
        'FAKE_DATABASE_DETAIL_MUST_NOT_APPEAR', 'raw database exception',
    ))
