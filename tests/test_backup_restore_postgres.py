"""Opt-in destructive logical backup/restore test for a disposable PostgreSQL DB."""

import os
import secrets
import shutil
import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from deploy import backup
from netbox_sync import deployment


TEST_DSN = os.environ.get('NETBOX_SYNC_BACKUP_TEST_POSTGRES_DSN', '')


def _environment(tmp_path):
    if not TEST_DSN:
        pytest.skip('NETBOX_SYNC_BACKUP_TEST_POSTGRES_DSN is not configured')
    parsed = conninfo_to_dict(TEST_DSN)
    if parsed.get('dbname') != 'netbox_sync_backup_test':
        pytest.fail('backup integration requires database netbox_sync_backup_test')
    if parsed.get('user') != 'netbox_sync_bootstrap':
        pytest.fail('backup integration requires user netbox_sync_bootstrap')
    if any(shutil.which(name) is None for name in ('pg_dump', 'pg_restore', 'psql')):
        pytest.skip('compatible PostgreSQL client tools are unavailable')
    root = tmp_path / 'passwords'
    root.mkdir()
    passwords = {'bootstrap': parsed.get('password', '')}
    passwords.update({key: secrets.token_urlsafe(24) for key in deployment.DATABASE_ROLES})
    for key, filename in deployment.PASSWORD_FILES.items():
        path = root / filename
        path.write_text(passwords[key] + '\n', encoding='utf-8')
        path.chmod(0o600)
    return {
        'NETBOX_SYNC_DB_HOST': parsed.get('host', '127.0.0.1'),
        'NETBOX_SYNC_DB_PORT': parsed.get('port', '5432'),
        'NETBOX_SYNC_DB_NAME': parsed['dbname'],
        'NETBOX_SYNC_DB_PASSWORD_DIR': str(root),
        'NETBOX_SYNC_REGISTRY_SCHEMA': 'netbox_sync',
    }


def _seed(connection):
    source_sql = """
        INSERT INTO netbox_sync.sources (
          id, source_instance, name, source_type, address, enabled, sync_enabled,
          sync_interval_seconds, verify_ssl, site_slug, device_role_slug,
          platform_slug, device_type_slug, cluster_type_slug, cluster_name,
          username, token_id_provider, token_id_key, token_secret_provider,
          token_secret_key, legacy_identity_owner, settings
        ) VALUES (
          %s, %s, %s, %s, %s, true, %s, %s, false, 'test-site', 'server',
          %s, 'generic', 'virtualization', %s, %s, 'file', %s, 'file', %s, %s, %s
        )
    """
    with connection.cursor() as cursor:
        cursor.execute(source_sql, (
            'pve-row', 'pve-backup-test', 'PVE backup test', 'proxmox', 'pve.invalid',
            True, 300, 'proxmox', 'PVE', 'root@pam', 'pve-token-id',
            'pve-token-secret', True, Jsonb({'unknown_future_key': 'preserved'})))
        cursor.execute(source_sql, (
            'esxi-row', 'esxi-backup-test', 'ESXi backup test', 'esxi', 'esxi.invalid',
            False, 600, 'vmware', 'ESXi', 'readonly', 'esxi-user',
            'esxi-password', False, Jsonb({'another_unknown_key': 7})))
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        cursor.execute(
            "INSERT INTO netbox_sync.sync_runs "
            "(run_id, source_instance, source_type, trigger, started_at, status, created_by) "
            "VALUES (%s, 'pve-backup-test', 'proxmox', 'scheduled', %s, "
            "'RUNNING', 'scheduler')", (uuid.uuid4(), started))
        cursor.execute(
            "INSERT INTO netbox_sync.sync_runs "
            "(run_id, source_instance, source_type, trigger, started_at, finished_at, "
            "duration_ms, status, created_by) VALUES "
            "(%s, 'esxi-backup-test', 'esxi', 'manual', %s, %s, 1000, "
            "'SUCCEEDED', 'operator')", (uuid.uuid4(), started, started))


def _snapshot(connection):
    with connection.cursor() as cursor:
        cursor.execute('SELECT * FROM netbox_sync.sources ORDER BY source_instance')
        sources = cursor.fetchall()
        cursor.execute('SELECT * FROM netbox_sync.sync_runs ORDER BY source_instance, run_id')
        runs = cursor.fetchall()
        cursor.execute('SELECT version_num FROM netbox_sync.alembic_version')
        revision = cursor.fetchone()[0]
    return sources, runs, revision


def test_custom_dump_round_trip_preserves_multi_source_and_history(tmp_path):
    """Includes distinct providers, intervals, refs, settings, and stale RUNNING."""
    environment = _environment(tmp_path)
    deployment.bootstrap_roles(environment)
    with psycopg.connect(deployment.connection_info('bootstrap', environment),
                         autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute('DROP SCHEMA IF EXISTS netbox_sync CASCADE')
    deployment.migrate(environment)
    deployment.apply_grants(environment)
    with psycopg.connect(deployment.connection_info('bootstrap', environment)) as connection:
        _seed(connection)
        connection.commit()
        connection.execute("UPDATE netbox_sync.sources SET enabled=false,sync_enabled=false WHERE source_instance='esxi-backup-test'")
        connection.execute("INSERT INTO netbox_sync.source_tombstones(source_instance,display_name,credential_state) VALUES ('esxi-backup-test','Retained ESXi','REMOVED')")
        connection.execute("INSERT INTO netbox_sync.source_operations(source_instance,operation_kind,operation_id,status) VALUES ('pve-backup-test','PLAN',%s,'RUNNING')", (uuid.uuid4(),))
        connection.commit()
        connection.execute("INSERT INTO netbox_sync.host_reservations(provider,anchor,source_instance,operation_id,actor_id) VALUES ('esxi','503c5ad7-aaaa-bbbb-cccc-0123456789ab','esxi-backup-test',%s,'admin')",(uuid.uuid4(),))
        connection.execute("INSERT INTO netbox_sync.source_recoveries(operation_id,source_instance,actor_id,revision,plan,state) VALUES (%s,'esxi-backup-test','admin','fixture-revision',%s,'CREDENTIALS_PENDING')",(uuid.uuid4(),Jsonb({'proof':{'digest':'a'*64},'credential_key':'src-recovery-fixture','broker_operation':'fixture-operation'})))
        connection.commit()
        connection.execute("INSERT INTO netbox_sync.registration_intents(source_instance,operation_id,actor_id,anchor,fingerprint) SELECT source_instance,operation_id,actor_id,anchor,%s FROM netbox_sync.host_reservations",('b'*64,))
        connection.execute("INSERT INTO netbox_sync.source_identity_verifications(operation_id,source_instance,actor_id,revision,anchor,proof) VALUES (%s,'esxi-backup-test','admin',%s,'503c5ad7-aaaa-bbbb-cccc-0123456789ab',%s)",(uuid.uuid4(),'c'*64,Jsonb({'owned':[{'kind':'device','id':7}],'blockers':[]})))
        connection.commit()
        connection.execute('UPDATE netbox_sync.registration_intents SET request=%s',(Jsonb({'fixture':'secret-free durable request'}),))
        connection.execute("INSERT INTO netbox_sync.run_reconciliations(run_id,source_instance,actor_id,operation_id,run_status,run_finished_at,decision) VALUES (%s,'esxi-backup-test','admin',%s,'OUTCOME_UNCERTAIN',clock_timestamp(),%s)",(uuid.uuid4(),uuid.uuid4(),Jsonb({'digest':'f'*64,'historical_outcome':'UNPROVED'})))
        connection.commit()
        expected_baselines=connection.execute('SELECT * FROM netbox_sync.run_reconciliations').fetchall()
        expected_intents=connection.execute('SELECT * FROM netbox_sync.registration_intents').fetchall()
        expected_identity=connection.execute('SELECT * FROM netbox_sync.source_identity_verifications').fetchall()
        connection.execute("INSERT INTO netbox_sync.source_retirements(operation_id,source_instance,actor_id,revision,guard_instance,plan,state,remove_credentials) VALUES (%s,'esxi-backup-test','admin',%s,%s,%s,'SENDING',false)",
            (uuid.uuid4(),'d'*64,uuid.uuid4(),Jsonb({'remote':{'digest':'e'*64,'manifest':{'format':2,'cluster_id':7,'objects':[['vm:8','f'*64]]}},'removal_generation':None,'source_flags':{'enabled':False,'sync_enabled':False}})))
        connection.commit()
        expected_retirements=connection.execute('SELECT * FROM netbox_sync.source_retirements').fetchall()
        expected_claims = connection.execute('SELECT * FROM netbox_sync.host_reservations').fetchall()
        expected_recoveries = connection.execute('SELECT * FROM netbox_sync.source_recoveries').fetchall()
        expected_tombstone = connection.execute('SELECT * FROM netbox_sync.source_tombstones').fetchall()
        expected = _snapshot(connection)

    from netbox_sync.auth_store import AuthStore
    auth = AuthStore(TEST_DSN, 'netbox_sync')
    invitation = auth.call({'action':'invite'}, root=True)['invitation']
    session = auth.call(dict(action='enroll', invitation=invitation, username='admin', password='test-only-password-9284'))['session']
    auth.call({'action':'managed','ceiling':'public-ipv4'}, root=True)
    auth.call(dict(action='policy.update',session=session,host='source.example.test',expected_revision=1,request_id='backup-policy'))
    with psycopg.connect(TEST_DSN) as connection:
        saved_auth = connection.execute('SELECT value FROM netbox_sync.auth_state').fetchone()[0]
        saved_audit = connection.execute('SELECT event FROM netbox_sync.auth_audit ORDER BY id').fetchall()

    tool = backup.DatabaseTool(
        tmp_path, 'external', {'NETBOX_SYNC_BACKUP_DSN': TEST_DSN})
    dump = tmp_path / 'database.dump'
    tool.dump(dump)
    tool.verify_dump(dump)
    assert tool.metadata()['source_count'] == 2
    assert tool.metadata()['run_count'] == 2

    with psycopg.connect(deployment.connection_info('bootstrap', environment),
                         autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute('DROP SCHEMA netbox_sync CASCADE')
    deployment.migrate(environment)
    assert tool.target_counts() == (0, 0)
    tool.restore(dump)
    deployment.migrate(environment)
    deployment.apply_grants(environment)
    with psycopg.connect(deployment.connection_info('bootstrap', environment)) as connection:
        assert _snapshot(connection) == expected
        assert connection.execute('SELECT * FROM netbox_sync.run_reconciliations').fetchall()==expected_baselines
        assert connection.execute('SELECT * FROM netbox_sync.registration_intents').fetchall()==expected_intents
        assert connection.execute('SELECT * FROM netbox_sync.source_identity_verifications').fetchall()==expected_identity
        assert connection.execute('SELECT * FROM netbox_sync.source_retirements').fetchall()==expected_retirements
        assert connection.execute('SELECT * FROM netbox_sync.host_reservations').fetchall() == expected_claims
        assert connection.execute('SELECT * FROM netbox_sync.source_recoveries').fetchall() == expected_recoveries
        assert connection.execute('SELECT * FROM netbox_sync.source_tombstones').fetchall() == expected_tombstone
        assert connection.execute('SELECT status FROM netbox_sync.source_operations').fetchone() == ('RUNNING',)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_get_userbyid(relowner) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='netbox_sync' AND relname='sources'")
            assert cursor.fetchone() == ('netbox_sync_owner',)
            cursor.execute("SELECT has_table_privilege('netbox_sync_web_reader', "
                           "'netbox_sync.sync_runs', 'SELECT')")
            assert cursor.fetchone() == (True,)

    with psycopg.connect(TEST_DSN) as connection:
        assert connection.execute('SELECT value FROM netbox_sync.auth_state').fetchone()[0] == saved_auth
        assert connection.execute('SELECT event FROM netbox_sync.auth_audit ORDER BY id').fetchall() == saved_audit
    tool.revoke_restored_auth()
    from netbox_sync.auth_policy import AuthError
    with pytest.raises(AuthError, match='AUTH_REQUIRED'):
        auth.call(dict(action='authorize',session=session))
    with psycopg.connect(TEST_DSN) as connection:
        assert connection.execute('SELECT valid,decision FROM netbox_sync.run_reconciliations').fetchone()==(False,{'digest':'f'*64,'historical_outcome':'UNPROVED'})
        restored_auth=connection.execute('SELECT value FROM netbox_sync.auth_state').fetchone()[0]
        assert restored_auth['principal']==saved_auth['principal']
        assert restored_auth['allowed_hosts']==saved_auth['allowed_hosts']
        assert restored_auth['sessions']=={} and restored_auth['invitation'] is None
        assert restored_auth['mode']=='legacy' and restored_auth['ceiling'] is None
    tool.reconcile_operations()
    with psycopg.connect(deployment.connection_info('bootstrap', environment)) as connection:
        assert connection.execute('SELECT status,safe_error_code,result FROM netbox_sync.source_operations').fetchone() == ('FAILED','OPERATION_INTERRUPTED',None)
        assert connection.execute('SELECT state,safe_code,receipt FROM netbox_sync.source_retirements').fetchone()==('UNCERTAIN','RETIREMENT_UNCERTAIN',None)
        assert connection.execute('SELECT * FROM netbox_sync.source_tombstones').fetchall() == expected_tombstone
    assert [row['source_instance'] for row in tool.source_secret_references()] == ['pve-backup-test']


def test_new_pending_records_prevent_fresh_restore_and_restored_sources_keep_refs(tmp_path):
    environment=_environment(tmp_path)
    deployment.bootstrap_roles(environment)
    with psycopg.connect(TEST_DSN,autocommit=True) as connection:
        connection.execute('DROP SCHEMA IF EXISTS netbox_sync CASCADE')
    deployment.migrate(environment);deployment.apply_grants(environment)
    tool=backup.DatabaseTool(tmp_path,'external',{'NETBOX_SYNC_BACKUP_DSN':TEST_DSN})
    with psycopg.connect(TEST_DSN) as connection:
        connection.execute("INSERT INTO netbox_sync.host_reservations(provider,anchor,source_instance,operation_id,actor_id) VALUES ('esxi','503c5ad7-aaaa-bbbb-cccc-0123456789ab','pending-source',%s,'admin')",(uuid.uuid4(),))
    with pytest.raises(backup.BackupError,match='host reservation or recovery'):
        tool.validate_empty_target()
    with psycopg.connect(TEST_DSN) as connection:
        _seed(connection)
        connection.execute("INSERT INTO netbox_sync.source_tombstones(source_instance,display_name,credential_state,restored_at) VALUES ('esxi-backup-test','Restored ESXi','REMOVED',now())")
    assert [row['source_instance'] for row in tool.source_secret_references()]==['esxi-backup-test','pve-backup-test']
