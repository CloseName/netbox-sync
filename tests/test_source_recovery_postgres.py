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
from netbox_sync.source_config import SourceCredentials,SecretReference
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


def test_completed_retirement_restores_namespace_when_cluster_is_gone(setup):
    from psycopg.types.json import Jsonb
    from netbox_sync.netbox_catalog import fingerprint
    store,registry,config,revision,old=setup
    source=config.source_instance;retirement=uuid4();guard=uuid4()
    receipt={'nonce':str(retirement),'source_instance':source,'status':'SUCCEEDED','digest':'e'*64,
        'manifest':{'format':2,'cluster_id':3,'objects':[['cluster:3','d'*64]]},'deleted':['cluster:3']}
    with store.connect() as connection:
        connection.execute(sql.SQL("INSERT INTO {} (operation_id,source_instance,actor_id,revision,guard_instance,plan,state,receipt,finished_at) VALUES (%s,%s,'admin',%s,%s,%s,'FINALIZED',%s,clock_timestamp()-interval '1 minute')").format(store.table('source_retirements')),
            (retirement,source,revision,guard,Jsonb({'remote':receipt}),Jsonb(receipt)))
    class Remote:
        present=False
        calls=[]
        def call(self,action,operation,**fields):
            self.calls.append(action)
            if action=='receipt':return {'guard_instance':str(guard),'result':receipt}
            assert action=='audit'
            result={'source_instance':source,'objects':[{'kind':'cluster','id':3,'present':self.present}], 'historical_outcome':'UNPROVED'}
            result['digest']=fingerprint(result)
            return {'guard_instance':str(guard),'result':result}
    remote=Remote();recovery=Recovery(store,remote);operation=uuid4()
    assert recovery.describe(source,'admin')['completed_retirement']
    remote.present=True
    blocked=recovery.retired_evidence(source,operation)
    with pytest.raises(LifecycleError):recovery.prepare(source,operation,'admin',revision,blocked)
    remote.present=False
    proof=recovery.retired_evidence(source,operation)
    assert proof['mode']=='RETIRED_EMPTY' and not proof['blockers'] and proof['placement_requires_review']
    recovery.prepare(source,operation,'admin',revision,proof)
    recovery.begin_credentials(source,operation,'admin')
    recovery.complete(source,operation,'admin',recovery.retired_evidence(source,operation),
        {'username':'service','address':config.address,'verify_ssl':True,'port':443},lambda *a:True)
    saved=registry.get_by_source_instance(source).config
    assert saved.enabled and not saved.sync_enabled and saved.source_instance==source
    assert saved.target==config.target  # Missing placement is explicitly repaired afterward.
    assert remote.calls==['receipt','audit']*3
    # A later retain-only removal must not inherit the previous retirement proof.
    view=store.read(source)
    store.remove(source,view['revision'],view['display_name'],False,lambda _:None)
    assert not recovery.describe(source,'admin')['completed_retirement']
    with pytest.raises(LifecycleError):recovery.retired_evidence(source,uuid4())


@pytest.mark.parametrize('enabled',[True,False])
def test_recovery_rejects_other_registered_identity_even_when_disabled(setup,enabled):
    store,registry,config,revision,proof=setup
    other=replace(config,id='esxi-second',source_instance='esxi-second',enabled=enabled,credentials=SourceCredentials(username='fixture',token_id=SecretReference('file','other-id'),token_secret=SecretReference('file','other-secret')))
    registry.create_source(other)
    with pytest.raises(LifecycleError,match='SOURCE_RECOVERY_IDENTITY_CONFLICT'):
        Recovery(store).prepare(config.source_instance,uuid4(),'admin',revision,proof)
    assert store.read(config.source_instance)['removed_at']


def test_three_retained_identity_records_are_reviewable_without_releasing_reserves(setup):
    import json
    store,registry,config,revision,proof=setup
    for index in range(2):
        other=replace(config,id=f'esxi-retained-{index}',source_instance=f'esxi-retained-{index}',name=f'Retained {index}',address=f'alias{index}.example',credentials=SourceCredentials(username='fixture',token_id=SecretReference('file',f'other-id-{index}'),token_secret=SecretReference('file',f'other-secret-{index}')))
        registry.create_source(other)
        row=store.read(other.source_instance)
        store.remove(other.source_instance,row['revision'],row['display_name'],False,lambda _:None)
    records=Recovery(store).records(config.source_instance)
    assert records['comparison']=='RECORDED_IDENTITY_ONLY'
    assert len(records['sources'])==3 and all(row['state']=='REMOVED' for row in records['sources'])
    assert all(row['host_uuid']==ANCHOR for row in records['sources'])
    assert all(row['cluster_id']==3 for row in records['sources'])
    assert 'token_secret' not in json.dumps(records) and 'credential_key' not in json.dumps(records)
    # Explicit recovery of one namespace is possible, but no historical record is deleted.
    operation=uuid4();Recovery(store).prepare(config.source_instance,operation,'admin',revision,proof)
    Recovery(store).begin_credentials(config.source_instance,operation,'admin')
    Recovery(store).complete(config.source_instance,operation,'admin',proof,{'username':'fixture','address':config.address,'verify_ssl':True,'port':443},lambda *args:True)
    after=Recovery(store).records(config.source_instance)
    assert [r['state'] for r in after['sources']].count('REGISTERED')==1
    assert len(after['sources'])==3
