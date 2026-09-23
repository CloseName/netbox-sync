"""Same-namespace recovery transactions on disposable PostgreSQL."""
from contextlib import contextmanager
from dataclasses import replace
from threading import Lock
from uuid import uuid4
from copy import deepcopy
import pytest
from psycopg import sql
from netbox_sync.source_lifecycle import LifecycleStore,LifecycleError
from netbox_sync.source_recovery import Recovery
from netbox_sync.recovery_evidence import assess
from tests.test_migrations_postgres import migration_database,_upgrade
from tests.test_source_registry_postgres import _safe_test_dsn
from tests.test_esxi_runtime import _config

ANCHOR='503c5ad7-aaaa-bbbb-cccc-0123456789ab'


@pytest.fixture
def setup(migration_database):
    registry,engine=migration_database;_upgrade(registry,engine)
    config=replace(_config(),settings={'onboarding_mapping':{'hosts':[{'id':ANCHOR,'name':'Host'}],
        'references':{'site':{'id':1},'cluster':{'id':3}}}})
    registry.create_source(config)
    gate=Lock()
    @contextmanager
    def lock(_):
        with gate:yield
    store=LifecycleStore(_safe_test_dsn(),registry.schema,'test-only',lock=lock)
    old=store.read(config.source_instance)
    store.remove(config.source_instance,old['revision'],old['display_name'],False,lambda _:None)
    row=store.connect()
    with row:
        raw=row.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s').format(store.table('sources')),
                        (config.source_instance,)).fetchone()
    proof=assess(config.source_instance,ANCHOR,1,3,{'id':3,'scope_type':'dcim.site','scope_id':1},[],[])
    return store,registry,config,store.revision(raw),proof


def test_restart_restore_and_repeat_keep_namespace_history_and_schedule_off(setup):
    store,registry,config,revision,proof=setup
    operation=uuid4();recovery=Recovery(store)
    prepared=recovery.prepare(config.source_instance,operation,'admin',revision,proof)
    assert prepared['state']=='PREPARED'
    ready=Recovery(store).begin_credentials(config.source_instance,operation,'admin')
    assert ready['state']=='CREDENTIALS_PENDING'
    metadata={'username':'new-service-account','address':config.address,'verify_ssl':True,'port':8443}
    with pytest.raises(LifecycleError,match='CREDENTIALS_UNCONFIRMED'):
        recovery.complete(config.source_instance,operation,'admin',proof,metadata,lambda *args:False)
    assert store.read(config.source_instance)['removed_at']
    checked=[]
    def verify(*args):checked.append(args);return True
    result=Recovery(store).complete(config.source_instance,operation,'admin',proof,metadata,verify)
    assert result['state']=='RESTORED'
    assert checked==[(prepared['plan']['credential_key'],prepared['plan']['broker_operation'])]
    current=registry.get_by_source_instance(config.source_instance).config
    assert current.id==config.id and current.target==config.target
    assert current.enabled and not current.sync_enabled and current.api_port==8443
    assert current.credentials.username=='new-service-account'
    assert current.settings['onboarding_mapping']==config.settings['onboarding_mapping']
    assert store.read(config.source_instance)['removed_at'] is None
    assert Recovery(store).complete(config.source_instance,operation,'admin',proof,metadata,
        lambda *args:pytest.fail('No repeated credential action'))['state']=='RESTORED'
    # A later removal is a new lifecycle event; old confirmation cannot undo it.
    view=store.read(config.source_instance)
    store.remove(config.source_instance,view['revision'],view['display_name'],False,lambda _:None)
    recovery.complete(config.source_instance,operation,'admin',proof,metadata,verify)
    assert store.read(config.source_instance)['removed_at']
    with store.connect() as connection:
        journal=connection.execute(sql.SQL('SELECT plan FROM {} WHERE operation_id=%s').format(
            store.table('source_recoveries')),(operation,)).fetchone()
        assert journal['plan']['removal']['removed_at']==prepared['plan']['removal']['removed_at']


def test_changed_identity_scope_and_actor_refuse_without_activation(setup):
    store,registry,config,revision,proof=setup
    recovery=Recovery(store);source=config.source_instance;operation=uuid4()
    for changed in ({**proof,'host_uuid':str(uuid4())},{**proof,'cluster_id':9},
                    {**proof,'blockers':['FOREIGN_SOURCE_IN_PLACEMENT']}):
        with pytest.raises(LifecycleError):recovery.prepare(source,uuid4(),'admin',revision,changed)
    recovery.prepare(source,operation,'admin',revision,proof)
    with pytest.raises(LifecycleError):recovery.begin_credentials(source,operation,'operator')
    assert not registry.get_by_source_instance(source).config.enabled
    assert recovery.abandon_prepared(source,operation,'admin')['state']=='ABANDONED'
    next_operation=uuid4()
    recovery.prepare(source,next_operation,'admin',revision,proof)
    recovery.begin_credentials(source,next_operation,'admin')
    with pytest.raises(LifecycleError,match='OUTCOME_UNCERTAIN'):
        recovery.abandon_prepared(source,next_operation,'admin')
    with pytest.raises(LifecycleError,match='ACTIVE'):
        recovery.prepare(source,uuid4(),'admin',revision,proof)


def test_concurrent_recovery_has_one_durable_attempt(setup):
    from concurrent.futures import ThreadPoolExecutor
    store,registry,config,revision,proof=setup
    operations=[uuid4(),uuid4()]
    def prepare(operation):
        try:return Recovery(store).prepare(config.source_instance,operation,'admin',revision,proof)['state']
        except LifecycleError as exc:return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(prepare,operations))
    assert sorted(results)==['PREPARED','SOURCE_RECOVERY_ACTIVE']
    assert not registry.get_by_source_instance(config.source_instance).config.enabled


def test_evidence_changes_after_credentials_never_activate_source(setup):
    store,registry,config,revision,proof=setup
    operation=uuid4();recovery=Recovery(store)
    recovery.prepare(config.source_instance,operation,'admin',revision,proof)
    recovery.begin_credentials(config.source_instance,operation,'admin')
    metadata={'username':'service-user','address':config.address,'verify_ssl':True,'port':443}
    changed={**proof,'digest':'f'*64}
    with pytest.raises(LifecycleError,match='EVIDENCE_CHANGED'):
        recovery.complete(config.source_instance,operation,'admin',changed,metadata,
            lambda *args:pytest.fail('No credential action after evidence mismatch'))
    assert not registry.get_by_source_instance(config.source_instance).config.enabled
    assert recovery.status(config.source_instance,operation,'admin')['state']=='CREDENTIALS_PENDING'
