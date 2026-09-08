"""Scheduled and manual apply paths share one narrowly mounted host lock."""

from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]


def test_scheduled_and_manual_apply_use_same_host_lock_directory():
    service = (ROOT / 'deploy' / 'systemd' / 'netbox-sync.service').read_text(
        encoding='utf-8'
    )
    compose = (ROOT / 'compose.production.yml').read_text(encoding='utf-8')
    wrapper = (ROOT / 'scripts' / 'run-scheduled-sync.sh').read_text(encoding='utf-8')
    assert 'ExecStartPre=/usr/bin/install -d -m 0750 /run/netbox-sync' in service
    assert 'ExecStart=@DEPLOYMENT_ROOT@/current/scripts/run-scheduled-sync.sh' in service
    assert '/usr/bin/flock -n /run/netbox-sync/apply.lock' in wrapper
    assert '/usr/bin/flock' not in service
    assert '${NETBOX_SYNC_APPLY_LOCK_DIR:-/run/netbox-sync}:/run/netbox-sync-lock' in compose
    assert '--lock-path, /run/netbox-sync-lock/apply.lock' in compose
    assert ':/run:/' not in compose


def test_scheduled_registry_all_apply_contract_is_unchanged():
    wrapper = (ROOT / 'scripts' / 'run-full-sync.sh').read_text(encoding='utf-8')
    for expected in ('SYNC_MODE=apply', 'APPLY_SCOPE=full', 'APPLY_CONFIRM=FULL_WRITE',
                     'docker compose', 'netbox-sync'):
        assert expected in wrapper


def test_exclusive_lock_allows_only_one_apply(tmp_path):
    """Linux flock rejects a concurrent manual/scheduled writer on the same inode."""
    try:
        import fcntl  # pylint: disable=import-outside-toplevel,import-error
    except ImportError:
        pytest.skip('flock is Linux-only')
    path = tmp_path / 'apply.lock'
    with path.open('w', encoding='utf-8') as scheduled, path.open('r+', encoding='utf-8') as manual:
        fcntl.flock(scheduled.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            fcntl.flock(manual.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_compose_keeps_apply_credentials_out_of_api_and_discovery_worker():
    """Only the dedicated apply service receives its reader DSN, token, and secret roots."""
    compose = (ROOT / 'compose.web.yml').read_text(encoding='utf-8')
    api, remainder = compose.split('  netbox-sync-secret-broker:', 1)
    discovery, apply = remainder.split('  netbox-sync-apply-worker:', 1)
    apply = apply.split('\nvolumes:', 1)[0]
    assert 'NETBOX_SYNC_APPLY_REGISTRY_DSN' not in api
    assert 'NETBOX_SYNC_RUN_WRITER_DSN' not in api
    assert 'netbox-apply-token' not in api
    assert 'NETBOX_SYNC_APPLY_REGISTRY_DSN' not in discovery
    assert 'NETBOX_SYNC_RUN_WRITER_DSN' not in discovery
    assert 'netbox-apply-token' not in discovery
    assert 'NETBOX_SYNC_REGISTRATION_DSN' not in apply
    assert 'NETBOX_SYNC_RUN_WRITER_DSN' in apply
    assert 'netbox-sync-broker-socket' not in apply
    assert 'docker.sock' not in compose


def test_scheduled_run_writer_credential_is_scoped_to_apply_override():
    base = Path('compose.yml').read_text(encoding='utf-8')
    apply = Path('compose.apply.yml').read_text(encoding='utf-8')
    assert 'NETBOX_SYNC_RUN_WRITER_DSN' not in base
    assert 'NETBOX_SYNC_RUN_WRITER_DSN' in apply
