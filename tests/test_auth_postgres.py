"""Transactional enrollment and policy races on disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
import psycopg
from psycopg import sql
from netbox_sync.auth_store import AuthStore
from netbox_sync.auth_policy import AuthError
from tests.test_migrations_postgres import migration_database, _upgrade
from tests.test_source_registry_postgres import _safe_test_dsn


def test_double_enrollment_and_policy_cas_are_serialized(migration_database):
    registry,engine=migration_database
    _upgrade(registry,engine)
    store=AuthStore(_safe_test_dsn(),registry.schema)
    invite=store.call({'action':'invite'},root=True)['invitation']
    barrier=Barrier(2)
    def enroll(_):
        barrier.wait()
        try:return store.call(dict(action='enroll',username='admin',password='test-only-password-9284',invitation=invite))
        except AuthError as e:return e.code
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(enroll,range(2)))
    assert sum(isinstance(v,dict) for v in results)==1
    assert 'ENROLLMENT_INVALID' in results
    session=next(v['session'] for v in results if isinstance(v,dict))
    store.call({'action':'managed','ceiling':'public-ipv4'},root=True)
    barrier=Barrier(2)
    def change(i):
        barrier.wait()
        try:return store.call(dict(action='policy.update',session=session,host=f'host{i}.example.test',expected_revision=1,request_id=f'request-{i}'))
        except AuthError as e:return e.code
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(change,range(2)))
    assert sum(isinstance(v,dict) for v in results)==1 and 'POLICY_CONFLICT' in results
    reopened=AuthStore(_safe_test_dsn(),registry.schema)
    assert reopened.call(dict(action='policy',session=session))['revision']==2
    with psycopg.connect(_safe_test_dsn()) as connection:
        events=connection.execute(sql.SQL('SELECT event FROM {}').format(sql.Identifier(registry.schema,'auth_audit'))).fetchall()
    assert sum(e[0]['action']=='policy.allow' for e in events)==1
    assert session not in str(events) and invite not in str(events)


def test_failed_login_rate_limit_survives_store_reopening(migration_database):
    registry,engine=migration_database;_upgrade(registry,engine)
    store=AuthStore(_safe_test_dsn(),registry.schema)
    for _ in range(5):
        with pytest.raises(AuthError,match='AUTH_INVALID'):
            store.call(dict(action='login',username='admin',password='not-real'))
    with pytest.raises(AuthError,match='AUTH_RATE_LIMITED'):
        AuthStore(_safe_test_dsn(),registry.schema).call(dict(action='login',username='admin',password='not-real'))


def test_upgrade_from_exact_pre_auth_head_preserves_source(migration_database):
    from alembic import command
    from alembic.config import Config
    from tests.sample_data import sample_source_config
    registry,engine=migration_database
    config=Config('alembic.ini');config.attributes['schema']=registry.schema
    with engine.connect() as connection:
        config.attributes['connection']=connection
        command.upgrade(config,'0005_source_tombstones')
    source=registry.create_source(sample_source_config())
    _upgrade(registry,engine)
    assert registry.get_source(source.id)==source
    store=AuthStore(_safe_test_dsn(),registry.schema)
    assert store.call({'action':'status'},root=True)=={'ready':True,'enrolled':False}
    with pytest.raises(AuthError,match='AUTH_REQUIRED'):
        store.call(dict(action='authorize',session='anonymous'))
