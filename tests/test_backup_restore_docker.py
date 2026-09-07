"""Opt-in Docker smoke for the exact bundled PostgreSQL client transport."""

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from deploy import backup, install


ROOT = Path(__file__).parents[1]


@pytest.mark.skipif(
    os.environ.get('NETBOX_SYNC_BACKUP_DOCKER_TEST') != '1',
    reason='set NETBOX_SYNC_BACKUP_DOCKER_TEST=1 for disposable Docker smoke',
)
def test_bundled_postgres_custom_dump_restore_transport(tmp_path):
    """Creates and removes a unique project/volume; it never accepts an external DSN."""
    if shutil.which('docker') is None:
        pytest.skip('Docker is unavailable')
    project = 'netbox-sync-backup-smoke-' + uuid.uuid4().hex[:10]
    root = tmp_path / 'foundation'
    prepared = install.prepare_layout(root, ROOT, 'backup-smoke', 'unused:backup-smoke')
    compose_path = prepared.config / 'compose.env'
    replacement = install._merged_config(  # pylint: disable=protected-access
        compose_path, {}, {
            'NETBOX_SYNC_COMPOSE_PROJECT': project,
            'NETBOX_SYNC_POSTGRES_VOLUME': project + '-data',
        })
    install._atomic_write(compose_path, replacement)  # pylint: disable=protected-access
    install.publish_configuration(prepared)
    install.activate_release(root, prepared.release)
    command = install.compose_command(root)
    try:
        subprocess.run([*command, 'up', '-d', 'postgres'], check=True)  # noqa: S603
        install._wait_for_postgres(  # pylint: disable=protected-access
            root, prepared.release, root / 'config')
        database = backup.DatabaseTool(root, 'bundled')
        database.query(
            "CREATE ROLE netbox_sync_owner LOGIN; "
            "ALTER DATABASE netbox_sync OWNER TO netbox_sync_owner; "
            "CREATE SCHEMA netbox_sync AUTHORIZATION netbox_sync_owner; "
            "SET ROLE netbox_sync_owner; "
            "CREATE TABLE netbox_sync.alembic_version(version_num text primary key); "
            "INSERT INTO netbox_sync.alembic_version VALUES ('0002_sync_run_history'); "
            "CREATE TABLE netbox_sync.schema_meta(key text primary key, value text); "
            "INSERT INTO netbox_sync.schema_meta VALUES ('schema_version', '1'); "
            "CREATE TABLE netbox_sync.sources(source_instance text, token_id_provider text, "
            "token_id_key text, token_secret_provider text, token_secret_key text); "
            "INSERT INTO netbox_sync.sources VALUES "
            "('pve-smoke', 'file', 'pve-id', 'file', 'pve-secret'), "
            "('esxi-smoke', 'file', 'esxi-user', 'file', 'esxi-password'); "
            "CREATE TABLE netbox_sync.source_operations(source_instance text); "
            "CREATE TABLE netbox_sync.source_tombstones(source_instance text); "
            "CREATE TABLE netbox_sync.sync_runs(run_id text, status text); "
            "INSERT INTO netbox_sync.sync_runs VALUES ('one', 'RUNNING')")
        assert database.metadata()['source_count'] == 2
        assert database.metadata()['run_count'] == 1
        assert database.validate_foundation_target() is None
        expected_refs = database.source_secret_references()
        dump = root / 'state/database.dump'
        database.dump(dump)
        database.verify_dump(dump)
        database.query("DELETE FROM netbox_sync.sources; DELETE FROM netbox_sync.sync_runs")
        assert database.target_counts() == (0, 0)
        database.restore(dump)
        assert database.metadata()['source_count'] == 2
        assert database.metadata()['run_count'] == 1
        assert database.source_secret_references() == expected_refs
    finally:
        subprocess.run([*command, 'down', '--volumes', '--remove-orphans'],  # noqa: S603
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
