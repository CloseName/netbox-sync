"""Opt-in destructive tests for a dedicated disposable PostgreSQL cluster."""

import os
import secrets

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from netbox_sync import deployment


TEST_DSN = os.environ.get('NETBOX_SYNC_DEPLOYMENT_TEST_POSTGRES_DSN', '')


def _environment(tmp_path):
    if not TEST_DSN:
        pytest.skip('NETBOX_SYNC_DEPLOYMENT_TEST_POSTGRES_DSN is not configured')
    parsed = conninfo_to_dict(TEST_DSN)
    if parsed.get('dbname') != 'netbox_sync_deployment_test':
        pytest.fail('deployment integration requires database netbox_sync_deployment_test')
    if parsed.get('user') != 'netbox_sync_bootstrap':
        pytest.fail('deployment integration requires user netbox_sync_bootstrap')
    secret_root = tmp_path / 'secrets'
    secret_root.mkdir()
    passwords = {'bootstrap': parsed.get('password', '')}
    passwords.update({key: secrets.token_urlsafe(24) for key in deployment.DATABASE_ROLES})
    for key, filename in deployment.PASSWORD_FILES.items():
        path = secret_root / filename
        path.write_text(passwords[key] + '\n', encoding='utf-8')
        path.chmod(0o600)
    return {
        'NETBOX_SYNC_DB_HOST': parsed.get('host', '127.0.0.1'),
        'NETBOX_SYNC_DB_PORT': parsed.get('port', '5432'),
        'NETBOX_SYNC_DB_NAME': parsed['dbname'],
        'NETBOX_SYNC_DB_PASSWORD_DIR': str(secret_root),
        'NETBOX_SYNC_REGISTRY_SCHEMA': 'netbox_sync',
    }


def test_clean_bootstrap_migrate_grants_and_idempotency(tmp_path):
    env = _environment(tmp_path)
    deployment.bootstrap_roles(env)
    deployment.validate_migration_ownership(env)
    deployment.migrate(env)
    deployment.apply_grants(env)
    deployment.bootstrap_roles(env)
    deployment.validate_migration_ownership(env)
    deployment.migrate(env)
    deployment.apply_grants(env)

    with psycopg.connect(deployment.connection_info('bootstrap', env)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM netbox_sync.alembic_version")
            assert cursor.fetchone() == ('0005_source_tombstones',)
            cursor.execute("SELECT count(*) FROM netbox_sync.sources")
            assert cursor.fetchone() == (0,)
            cursor.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
                           (list(deployment.DATABASE_ROLES.values()),))
            assert {row[0] for row in cursor.fetchall()} == set(
                deployment.DATABASE_ROLES.values())
            cursor.execute("SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication "
                           "FROM pg_roles WHERE rolname = ANY(%s)",
                           (list(deployment.DATABASE_ROLES.values()),))
            assert all(row[1:] == (False, False, False, False) for row in cursor.fetchall())
            cursor.execute("SELECT pg_get_userbyid(datdba) FROM pg_database "
                           "WHERE datname='netbox_sync_deployment_test'")
            assert cursor.fetchone() == (deployment.DATABASE_ROLES['owner'],)


def test_runtime_role_grants_are_column_limited(tmp_path):
    env = _environment(tmp_path)
    deployment.bootstrap_roles(env)
    deployment.migrate(env)
    deployment.apply_grants(env)
    checks = {
        'discovery_reader': ('SELECT', 'sources'),
        'apply_registry_reader': ('SELECT', 'sources'),
        'registry_reader': ('SELECT', 'sources'),
    }
    with psycopg.connect(deployment.connection_info('bootstrap', env)) as connection:
        with connection.cursor() as cursor:
            for key, (allowed, table) in checks.items():
                role = deployment.DATABASE_ROLES[key]
                cursor.execute('SELECT has_table_privilege(%s, %s, %s)',
                               (role, f'netbox_sync.{table}', allowed))
                assert cursor.fetchone() == (True,)
                cursor.execute('SELECT has_table_privilege(%s, %s, %s)',
                               (role, f'netbox_sync.{table}', 'DELETE'))
                assert cursor.fetchone() == (False,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['run_writer'],
                            'netbox_sync.sync_runs', 'run_id', 'INSERT'))
            assert cursor.fetchone() == (True,)
            cursor.execute('SELECT has_table_privilege(%s, %s, %s)',
                           (deployment.DATABASE_ROLES['run_writer'],
                            'netbox_sync.sync_runs', 'DELETE'))
            assert cursor.fetchone() == (False,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['web_reader'],
                            'netbox_sync.sources', 'source_instance', 'SELECT'))
            assert cursor.fetchone() == (True,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['web_reader'],
                            'netbox_sync.sources', 'username', 'SELECT'))
            assert cursor.fetchone() == (False,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['registration_writer'],
                            'netbox_sync.sources', 'id', 'INSERT'))
            assert cursor.fetchone() == (True,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['registration_writer'],
                            'netbox_sync.sources', 'created_at', 'INSERT'))
            assert cursor.fetchone() == (False,)
            cursor.execute('SELECT has_table_privilege(%s, %s, %s)',
                           (deployment.DATABASE_ROLES['registration_writer'],
                            'netbox_sync.sources', 'UPDATE'))
            assert cursor.fetchone() == (False,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['schedule_writer'],
                            'netbox_sync.sources', 'sync_enabled', 'UPDATE'))
            assert cursor.fetchone() == (True,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['schedule_writer'],
                            'netbox_sync.sources', 'name', 'UPDATE'))
            assert cursor.fetchone() == (False,)
            cursor.execute('SELECT has_column_privilege(%s, %s, %s, %s)',
                           (deployment.DATABASE_ROLES['run_writer'],
                            'netbox_sync.sync_runs', 'status', 'UPDATE'))
            assert cursor.fetchone() == (True,)
            cursor.execute('SELECT has_table_privilege(%s, %s, %s)',
                           (deployment.DATABASE_ROLES['run_writer'],
                            'netbox_sync.sources', 'SELECT'))
            assert cursor.fetchone() == (False,)


def test_migration_ownership_preflight_rejects_foreign_schema_owner(tmp_path):
    env = _environment(tmp_path)
    deployment.bootstrap_roles(env)
    deployment.migrate(env)
    owner = deployment.DATABASE_ROLES['owner']
    foreign = deployment.DATABASE_ROLES['discovery_reader']
    with psycopg.connect(deployment.connection_info('bootstrap', env), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('ALTER SCHEMA netbox_sync OWNER TO {}').format(
                sql.Identifier(foreign)))
    try:
        with pytest.raises(deployment.DeploymentError, match='schema owner'):
            deployment.validate_migration_ownership(env)
    finally:
        with psycopg.connect(
                deployment.connection_info('bootstrap', env), autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('ALTER SCHEMA netbox_sync OWNER TO {}').format(
                    sql.Identifier(owner)))


def test_ui6_writers_have_only_the_required_capabilities(tmp_path):
    env = _environment(tmp_path)
    deployment.bootstrap_roles(env); deployment.migrate(env); deployment.apply_grants(env)
    with psycopg.connect(deployment.connection_info('bootstrap', env)) as connection:
        for key in ('operation_writer','lifecycle_writer'):
            role = deployment.DATABASE_ROLES[key]
            for table in ('sources','source_operations','source_tombstones','sync_runs'):
                for privilege in ('DELETE','TRUNCATE','TRIGGER','REFERENCES'):
                    assert connection.execute('SELECT has_table_privilege(%s,%s,%s)',
                        (role,'netbox_sync.'+table,privilege)).fetchone()==(False,)
            assert connection.execute('SELECT has_schema_privilege(%s,%s,%s)',(role,'netbox_sync','CREATE')).fetchone()==(False,)
        for key, table, column, allowed in (
            ('lifecycle_writer','sources','enabled',True),
            ('lifecycle_writer','sources','sync_enabled',True),
            ('lifecycle_writer','sources','source_instance',False),
            ('lifecycle_writer','sources','token_secret_key',False),
            ('operation_writer','sources','enabled',False),
            ('operation_writer','source_operations','status',True),
            ('web_reader','source_operations','status',False),
            ('apply_registry_reader','source_operations','status',False)):
            assert connection.execute('SELECT has_column_privilege(%s,%s,%s,%s)',
                (deployment.DATABASE_ROLES[key],'netbox_sync.'+table,column,'UPDATE')).fetchone()==(allowed,)
    for key in ('operation_writer','lifecycle_writer'):
        for statement in ('DELETE FROM netbox_sync.sources','TRUNCATE netbox_sync.source_operations',
                          'CREATE TABLE netbox_sync.forbidden(id integer)',
                          "UPDATE netbox_sync.sources SET source_instance='stolen'"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with psycopg.connect(deployment.connection_info(key, env)) as connection:
                    connection.execute(statement)
