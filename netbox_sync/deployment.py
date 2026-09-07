"""Operator-only PostgreSQL bootstrap and migration commands.

Credentials are read from protected files and never accepted on the command line.
This module is included in the application image but is not imported by runtime
services.
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.conninfo import make_conninfo

from .source_registry import SCHEMA_NAME_PATTERN


DATABASE_NAME = 'netbox_sync'
SCHEMA_NAME = 'netbox_sync'
BOOTSTRAP_ROLE = 'netbox_sync_bootstrap'
LEGACY_DATABASE_NAME = 'infra_sync'
LEGACY_SCHEMA_NAME = 'infra_sync'
LEGACY_BOOTSTRAP_ROLE = 'infra_sync_bootstrap'
DATABASE_ROLES = {
    key: f'netbox_sync_{key}' for key in (
        'owner', 'web_reader', 'registration_writer', 'discovery_reader',
        'apply_registry_reader', 'registry_reader', 'run_writer', 'schedule_writer',
        'operation_writer', 'lifecycle_writer')
}
LEGACY_DATABASE_ROLES = {key: f'infra_sync_{key}' for key in DATABASE_ROLES
                         if key not in {'operation_writer', 'lifecycle_writer'}}
NAMING_CONFIRMATION = 'RENAME_INFRA_SYNC_DATABASE_TO_NETBOX_SYNC'
PASSWORD_FILES = {
    'bootstrap': 'postgres_bootstrap_password',
    **{key: key + '_password' for key in DATABASE_ROLES},
}
RESTORE_BOOTSTRAP_FILE = 'postgres_bootstrap_password_next'
SOURCE_COLUMNS = (
    'id', 'source_instance', 'name', 'source_type', 'address', 'enabled',
    'sync_enabled', 'sync_interval_seconds', 'verify_ssl', 'site_slug',
    'device_role_slug', 'platform_slug', 'device_type_slug', 'cluster_type_slug',
    'cluster_name', 'username', 'token_id_provider', 'token_id_key',
    'token_secret_provider', 'token_secret_key', 'legacy_identity_owner', 'settings',
    'created_at', 'updated_at',
)
PUBLIC_SOURCE_COLUMNS = (
    'source_instance', 'source_type', 'name', 'address', 'enabled',
    'sync_enabled', 'verify_ssl', 'sync_interval_seconds', 'site_slug',
    'cluster_name', 'platform_slug', 'device_role_slug', 'device_type_slug',
    'cluster_type_slug', 'legacy_identity_owner',
)
REGISTRATION_INSERT_COLUMNS = SOURCE_COLUMNS[:-2]
RUN_INSERT_COLUMNS = (
    'run_id', 'source_instance', 'source_type', 'trigger', 'started_at', 'status',
    'plan_digest', 'planner_version', 'created_by',
)
RUN_UPDATE_COLUMNS = (
    'finished_at', 'duration_ms', 'status', 'plan_digest', 'planner_version',
    'create_count', 'update_count', 'no_change_count', 'review_required_count',
    'blocked_count', 'ignored_count', 'unsupported_count', 'retain_only_count',
    'error_code', 'error_message_safe',
)


class DeploymentError(RuntimeError):
    """Safe operator-facing deployment failure."""


def _required_setting(name, environ=None):
    value = (environ or os.environ).get(name, '').strip()
    if not value:
        raise DeploymentError(f'{name} is required')
    return value


def read_password(key, environ=None):
    """Read one bounded single-line password from the dedicated directory."""
    environ = environ or os.environ
    root = Path(_required_setting('NETBOX_SYNC_DB_PASSWORD_DIR', environ))
    filename = PASSWORD_FILES[key]
    path = root / filename
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            raise DeploymentError(f'invalid credential file: {filename}')
        value = path.read_text(encoding='utf-8').rstrip('\r\n')
    except OSError as exc:
        raise DeploymentError(f'credential file unavailable: {filename}') from exc
    if not value or '\n' in value or '\r' in value:
        raise DeploymentError(f'invalid credential file: {filename}')
    return value


def connection_info(role_key, environ=None):
    """Build libpq configuration without putting credentials in argv or logs."""
    environ = environ or os.environ
    role = (BOOTSTRAP_ROLE if role_key == 'bootstrap'
            else DATABASE_ROLES[role_key])
    return make_conninfo(
        host=_required_setting('NETBOX_SYNC_DB_HOST', environ),
        port=environ.get('NETBOX_SYNC_DB_PORT', '5432'),
        dbname=environ.get('NETBOX_SYNC_DB_NAME', DATABASE_NAME),
        user=role,
        password=read_password(role_key, environ),
        connect_timeout='5',
    )


def _execute_role(cursor, role, password):
    cursor.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (role,))
    if cursor.fetchone() is None:
        cursor.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(role)))
    # PostgreSQL utility statements don't accept bind parameters for PASSWORD.
    # psycopg.sql.Literal performs driver quoting; the composed query is never logged.
    cursor.execute(sql.SQL(
        'ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB '
        'NOCREATEROLE NOINHERIT NOREPLICATION'
    ).format(sql.Identifier(role), sql.Literal(password)))


def _rotate_bootstrap_password(cursor, password):
    """Rotate the privileged bootstrap login without changing its attributes."""
    cursor.execute(sql.SQL(
        'ALTER ROLE {} WITH LOGIN PASSWORD {}'
    ).format(sql.Identifier(BOOTSTRAP_ROLE), sql.Literal(password)))


def _legacy_connection_info(database, environ):
    return make_conninfo(
        host=_required_setting('NETBOX_SYNC_DB_HOST', environ),
        port=environ.get('NETBOX_SYNC_DB_PORT', '5432'), dbname=database,
        user=LEGACY_BOOTSTRAP_ROLE, password=read_password('bootstrap', environ),
        connect_timeout='5')


def _validate_legacy_schema(cursor):
    cursor.execute(
        'SELECT nspname FROM pg_namespace WHERE nspname IN (%s, %s)',
        (LEGACY_SCHEMA_NAME, SCHEMA_NAME))
    if {row[0] for row in cursor.fetchall()} != {LEGACY_SCHEMA_NAME}:
        raise DeploymentError('legacy and target schema naming conflict')
    cursor.execute(
        'SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename',
        (LEGACY_SCHEMA_NAME,))
    tables = tuple(row[0] for row in cursor.fetchall())
    if tables not in {
            ('alembic_version', 'schema_meta', 'sources'),
            ('alembic_version', 'schema_meta', 'sources', 'sync_runs')}:
        raise DeploymentError('legacy schema is not a recognized Foundation schema')
    cursor.execute(sql.SQL('SELECT version_num FROM {}.alembic_version').format(
        sql.Identifier(LEGACY_SCHEMA_NAME)))
    if cursor.fetchone()[0] not in {'0001_registry_baseline', '0002_sync_run_history'}:
        raise DeploymentError('legacy Alembic state is unsupported')


def migrate_database_naming(environ=None):
    """Rename preflighted state, preserving rows and legacy roles for rollback."""
    environ = environ or os.environ
    if environ.get('NETBOX_SYNC_NAMING_CONFIRM') != NAMING_CONFIRMATION:
        raise DeploymentError('explicit database naming confirmation is required')
    passwords = {key: read_password(key, environ)
                 for key in ('bootstrap', *DATABASE_ROLES)}
    with psycopg.connect(_legacy_connection_info(LEGACY_DATABASE_NAME, environ)) as connection:
        with connection.cursor() as cursor:
            _validate_legacy_schema(cursor)

    with psycopg.connect(
            _legacy_connection_info('postgres', environ), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT datname FROM pg_database WHERE datname IN (%s, %s)',
                (LEGACY_DATABASE_NAME, DATABASE_NAME))
            if {row[0] for row in cursor.fetchall()} != {LEGACY_DATABASE_NAME}:
                raise DeploymentError('legacy and target database naming conflict')
            legacy_roles = (LEGACY_BOOTSTRAP_ROLE, *LEGACY_DATABASE_ROLES.values())
            target_roles = (BOOTSTRAP_ROLE, *DATABASE_ROLES.values())
            cursor.execute(
                'SELECT rolname FROM pg_roles WHERE rolname=ANY(%s)',
                (list((*legacy_roles, *target_roles)),))
            if {row[0] for row in cursor.fetchall()} != set(legacy_roles):
                raise DeploymentError('legacy and target role naming conflict')
            cursor.execute(
                'SELECT count(*) FROM pg_stat_activity '
                'WHERE datname=%s AND pid<>pg_backend_pid()',
                (LEGACY_DATABASE_NAME,))
            if cursor.fetchone()[0]:
                raise DeploymentError('legacy database still has active connections')
            for key in DATABASE_ROLES:
                _execute_role(cursor, DATABASE_ROLES[key], passwords[key])
            cursor.execute(sql.SQL('CREATE ROLE {} LOGIN SUPERUSER PASSWORD {}').format(
                sql.Identifier(BOOTSTRAP_ROLE), sql.Literal(passwords['bootstrap'])))
            cursor.execute(sql.SQL('ALTER DATABASE {} RENAME TO {}').format(
                sql.Identifier(LEGACY_DATABASE_NAME), sql.Identifier(DATABASE_NAME)))
            cursor.execute(sql.SQL('ALTER DATABASE {} OWNER TO {}').format(
                sql.Identifier(DATABASE_NAME), sql.Identifier(DATABASE_ROLES['owner'])))
            cursor.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(
                sql.Identifier(DATABASE_NAME), sql.Identifier(BOOTSTRAP_ROLE)))

    with psycopg.connect(connection_info('bootstrap', environ), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('ALTER SCHEMA {} RENAME TO {}').format(
                sql.Identifier(LEGACY_SCHEMA_NAME), sql.Identifier(SCHEMA_NAME)))
            cursor.execute(sql.SQL('ALTER SCHEMA {} OWNER TO {}').format(
                sql.Identifier(SCHEMA_NAME), sql.Identifier(DATABASE_ROLES['owner'])))
            cursor.execute(
                "SELECT c.relname, c.relkind FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=%s AND c.relkind IN ('r', 'S') ORDER BY c.relname",
                (SCHEMA_NAME,))
            for name, kind in cursor.fetchall():
                object_type = sql.SQL('TABLE') if kind == 'r' else sql.SQL('SEQUENCE')
                cursor.execute(sql.SQL('ALTER {} {}.{} OWNER TO {}').format(
                    object_type, sql.Identifier(SCHEMA_NAME), sql.Identifier(name),
                    sql.Identifier(DATABASE_ROLES['owner'])))


def bootstrap_roles(environ=None):
    """Create/rotate fixed runtime roles and establish private DB ownership."""
    environ = environ or os.environ
    database = environ.get('NETBOX_SYNC_DB_NAME', DATABASE_NAME)
    with psycopg.connect(connection_info('bootstrap', environ), autocommit=True) as connection:
        with connection.cursor() as cursor:
            for key, role in DATABASE_ROLES.items():
                _execute_role(cursor, role, read_password(key, environ))
                read_only = key in {
                    'web_reader', 'discovery_reader', 'apply_registry_reader',
                    'registry_reader',
                }
                cursor.execute(sql.SQL(
                    'ALTER ROLE {} SET default_transaction_read_only={}'
                ).format(sql.Identifier(role), sql.SQL('on' if read_only else 'off')))
            cursor.execute(sql.SQL('ALTER DATABASE {} OWNER TO {}').format(
                sql.Identifier(database), sql.Identifier(DATABASE_ROLES['owner'])))
            cursor.execute(sql.SQL('REVOKE CONNECT, TEMP ON DATABASE {} FROM PUBLIC').format(
                sql.Identifier(database)))
            for role in DATABASE_ROLES.values():
                cursor.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(
                    sql.Identifier(database), sql.Identifier(role)))


def restore_role_passwords(environ=None):
    """Rotate fixed roles to restored files, changing bootstrap last.

    The password directory is a short-lived, root-only restore staging directory.
    Its ordinary bootstrap file contains the current target password while the
    fixed ``*_password`` files contain the restored runtime passwords.  Changing
    the bootstrap role last keeps the provisioning connection recoverable.
    """
    environ = environ or os.environ
    bootstrap_next = Path(_required_setting('NETBOX_SYNC_DB_PASSWORD_DIR', environ)) / \
        RESTORE_BOOTSTRAP_FILE
    try:
        if (bootstrap_next.is_symlink() or not bootstrap_next.is_file()
                or bootstrap_next.stat().st_size > 4096):
            raise DeploymentError('invalid restored bootstrap credential file')
        next_password = bootstrap_next.read_text(encoding='utf-8').rstrip('\r\n')
    except OSError as exc:
        raise DeploymentError('restored bootstrap credential unavailable') from exc
    if not next_password or '\n' in next_password or '\r' in next_password:
        raise DeploymentError('invalid restored bootstrap credential file')

    bootstrap_roles(environ)
    with psycopg.connect(connection_info('bootstrap', environ), autocommit=True) as connection:
        with connection.cursor() as cursor:
            _rotate_bootstrap_password(cursor, next_password)


def validate_migration_ownership(environ=None):
    """Fail before Alembic if an existing registry is owned by another role."""
    environ = environ or os.environ
    schema = environ.get('NETBOX_SYNC_REGISTRY_SCHEMA', SCHEMA_NAME)
    if not SCHEMA_NAME_PATTERN.fullmatch(schema):
        raise DeploymentError('NETBOX_SYNC_REGISTRY_SCHEMA is invalid')
    expected = DATABASE_ROLES['owner']
    with psycopg.connect(connection_info('owner', environ)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()')
            database_owner = cursor.fetchone()
            if database_owner is None or database_owner[0] != expected:
                raise DeploymentError(
                    'existing registry ownership is incompatible; inspect database owner')
            cursor.execute(
                'SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname=%s',
                (schema,),
            )
            schema_owner = cursor.fetchone()
            if schema_owner is None:
                return
            if schema_owner[0] != expected:
                raise DeploymentError(
                    'existing registry ownership is incompatible; inspect schema owner')
            cursor.execute(
                'SELECT c.relname, pg_get_userbyid(c.relowner) '
                'FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace '
                "WHERE n.nspname=%s AND c.relkind IN ('r', 'p')",
                (schema,),
            )
            if any(owner != expected for _name, owner in cursor.fetchall()):
                raise DeploymentError(
                    'existing registry ownership is incompatible; inspect table owners')


def migrate(environ=None):
    """Run the reviewed Alembic chain as owner, using an injected connection."""
    environ = environ or os.environ
    schema = environ.get('NETBOX_SYNC_REGISTRY_SCHEMA', SCHEMA_NAME)
    if not SCHEMA_NAME_PATTERN.fullmatch(schema):
        raise DeploymentError('NETBOX_SYNC_REGISTRY_SCHEMA is invalid')
    validate_migration_ownership(environ)
    engine = sa.create_engine(
        'postgresql+psycopg://',
        creator=lambda: psycopg.connect(connection_info('owner', environ)),
        poolclass=sa.pool.NullPool,
        hide_parameters=True,
    )
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    config.attributes['schema'] = schema
    try:
        with engine.connect() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
    finally:
        engine.dispose()


def _columns(names):
    return sql.SQL(', ').join(sql.Identifier(name) for name in names)


def _grant_columns(cursor, privilege, table, columns, role):
    cursor.execute(sql.SQL('GRANT {} ({}) ON {} TO {}').format(
        sql.SQL(privilege), _columns(columns), table, sql.Identifier(role)))


def apply_grants(environ=None):
    """Reapply the complete least-privilege matrix after every migration."""
    environ = environ or os.environ
    schema = environ.get('NETBOX_SYNC_REGISTRY_SCHEMA', SCHEMA_NAME)
    if not SCHEMA_NAME_PATTERN.fullmatch(schema):
        raise DeploymentError('NETBOX_SYNC_REGISTRY_SCHEMA is invalid')
    owner = DATABASE_ROLES['owner']
    sources = sql.Identifier(schema, 'sources')
    meta = sql.Identifier(schema, 'schema_meta')
    runs = sql.Identifier(schema, 'sync_runs')
    with psycopg.connect(connection_info('owner', environ)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(
                sql.Identifier(schema)))
            cursor.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM PUBLIC').format(
                sql.Identifier(schema)))
            cursor.execute(sql.SQL('REVOKE ALL ON ALL SEQUENCES IN SCHEMA {} FROM PUBLIC').format(
                sql.Identifier(schema)))
            cursor.execute(sql.SQL(
                'ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} '
                'REVOKE ALL ON TABLES FROM PUBLIC'
            ).format(sql.Identifier(owner), sql.Identifier(schema)))
            cursor.execute(sql.SQL(
                'ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} '
                'REVOKE ALL ON SEQUENCES FROM PUBLIC'
            ).format(sql.Identifier(owner), sql.Identifier(schema)))
            cursor.execute(sql.SQL(
                'ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} '
                'REVOKE ALL ON FUNCTIONS FROM PUBLIC'
            ).format(sql.Identifier(owner), sql.Identifier(schema)))
            for role in (value for key, value in DATABASE_ROLES.items() if key != 'owner'):
                cursor.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}').format(
                    sql.Identifier(schema), sql.Identifier(role)))
                cursor.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
                    sql.Identifier(schema), sql.Identifier(role)))

            for key in ('web_reader', 'registration_writer', 'discovery_reader',
                        'apply_registry_reader', 'registry_reader'):
                cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                    meta, sql.Identifier(DATABASE_ROLES[key])))
            _grant_columns(cursor, 'SELECT', sources, PUBLIC_SOURCE_COLUMNS,
                           DATABASE_ROLES['web_reader'])
            cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                runs, sql.Identifier(DATABASE_ROLES['web_reader'])))
            cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                sources, sql.Identifier(DATABASE_ROLES['registration_writer'])))
            _grant_columns(cursor, 'INSERT', sources, REGISTRATION_INSERT_COLUMNS,
                           DATABASE_ROLES['registration_writer'])
            for key in ('discovery_reader', 'apply_registry_reader', 'registry_reader'):
                cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                    sources, sql.Identifier(DATABASE_ROLES[key])))
            cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                runs, sql.Identifier(DATABASE_ROLES['run_writer'])))
            _grant_columns(cursor, 'INSERT', runs, RUN_INSERT_COLUMNS,
                           DATABASE_ROLES['run_writer'])
            _grant_columns(cursor, 'UPDATE', runs, RUN_UPDATE_COLUMNS,
                           DATABASE_ROLES['run_writer'])
            _grant_columns(cursor, 'SELECT', sources,
                           ('source_instance', 'sync_enabled', 'sync_interval_seconds'),
                           DATABASE_ROLES['schedule_writer'])
            _grant_columns(cursor, 'UPDATE', sources,
                           ('sync_enabled', 'sync_interval_seconds'),
                           DATABASE_ROLES['schedule_writer'])

            operations = sql.Identifier(schema, 'source_operations')
            tombstones = sql.Identifier(schema, 'source_tombstones')
            for key in ('web_reader', 'registration_writer', 'schedule_writer', 'lifecycle_writer'):
                cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                    tombstones, sql.Identifier(DATABASE_ROLES[key])))
            cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                operations, sql.Identifier(DATABASE_ROLES['apply_registry_reader'])))
            _grant_columns(cursor, 'SELECT', sources, ('source_instance','enabled'),
                           DATABASE_ROLES['operation_writer'])
            for privilege in ('SELECT','INSERT','UPDATE'):
                cursor.execute(sql.SQL('GRANT {} ON {} TO {}').format(sql.SQL(privilege),
                    operations, sql.Identifier(DATABASE_ROLES['operation_writer'])))
            for table in (sources, operations, runs):
                cursor.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(
                    table, sql.Identifier(DATABASE_ROLES['lifecycle_writer'])))
            _grant_columns(cursor, 'UPDATE', sources, ('enabled','sync_enabled'),
                           DATABASE_ROLES['lifecycle_writer'])
            _grant_columns(cursor, 'INSERT', tombstones,
                           ('source_instance','display_name','credential_state'),
                           DATABASE_ROLES['lifecycle_writer'])
            _grant_columns(cursor, 'UPDATE', tombstones, ('credential_state',),
                           DATABASE_ROLES['lifecycle_writer'])


def main(argv=None):
    """Run one explicit provisioning operation with sanitized failures."""
    parser = argparse.ArgumentParser(description='NetBox Sync deployment database tool')
    parser.add_argument('operation', choices=(
        'bootstrap-roles', 'migrate', 'apply-grants', 'restore-role-passwords',
        'migrate-naming'))
    args = parser.parse_args(argv)
    actions = {
        'bootstrap-roles': bootstrap_roles,
        'migrate': migrate,
        'apply-grants': apply_grants,
        'restore-role-passwords': restore_role_passwords,
        'migrate-naming': migrate_database_naming,
    }
    try:
        actions[args.operation]()
    except Exception:  # pylint: disable=broad-exception-caught
        print(f'{args.operation} failed; inspect protected database configuration', file=sys.stderr)
        return 1
    print(f'{args.operation} completed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
