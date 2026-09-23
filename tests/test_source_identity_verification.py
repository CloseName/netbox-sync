"""Legacy identity requires fresh provider UUID and existing source provenance."""
from contextlib import contextmanager
from dataclasses import replace
from threading import Lock
from uuid import uuid4
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest
from netbox_sync.source_identity_verification import IdentityVerification
from netbox_sync.source_lifecycle import LifecycleStore,LifecycleError
from netbox_sync.host_registration import legacy_anchor,HostReservations,HostRegistrationConflict
from netbox_sync.recovery_evidence import assess
from netbox_sync.netbox_catalog import fingerprint
from tests.test_migrations_postgres import migration_database,_upgrade
from tests.test_source_registry_postgres import _safe_test_dsn
from tests.test_esxi_runtime import _config
from tests.test_host_registration import ANCHOR,preview


@pytest.fixture
def identity_fixture(migration_database):
    registry,engine=migration_database;_upgrade(registry,engine)
    config=replace(_config(),settings={'preserved':'operator-setting'})
    registry.create_source(config)
    gate=Lock()
    @contextmanager
    def lock(_):
        with gate:yield
    store=LifecycleStore(_safe_test_dsn(),registry.schema,'fixture-only',lock=lock)
    operation=uuid4();source=config.source_instance
    with store.connect() as connection:
        connection.execute(sql.SQL("INSERT INTO {} (source_instance,operation_kind,operation_id,status,result,finished_at) VALUES (%s,'DISCOVERY',%s,'SUCCEEDED',%s,clock_timestamp())").format(store.table('source_operations')),
            (source,operation,Jsonb({'source_instance':source,'hosts':[{'id':ANCHOR,'name':'Same name','memory_bytes':0}]})))
    meta=IdentityVerification(store).describe(source)
    host={'id':7,'cluster':{'id':3},'custom_fields':{'sync_identities':[{'schema':'v2','type':'esxi','instance':source,'kind':'host','external_id':ANCHOR}]}}
    proof=assess(source,ANCHOR,1,3,{'id':3,'scope_type':'dcim.site','scope_id':1},[host],[],require_host=True)
    proof['configured_target']={'site_slug':config.target.site_slug,'cluster_name':config.target.cluster_name}
    proof.pop('digest');proof['digest']=fingerprint(proof)
    return store,registry,config,meta,proof


def test_verification_preserves_source_and_fences_old_plan(identity_fixture):
    store,registry,config,meta,proof=identity_fixture;source=config.source_instance
    with store.connect() as connection:
        connection.execute(sql.SQL("INSERT INTO {} (source_instance,operation_kind,operation_id,status,result) VALUES (%s,'PLAN',%s,'READY','{{}}')").format(store.table('source_operations')),(source,uuid4()))
    verifier=IdentityVerification(store)
    result=verifier.confirm(source,'admin',meta['revision'],meta['discovery_id'],proof)
    assert result['status']=='VERIFIED'
    after=registry.get_by_source_instance(source).config
    assert replace(after,settings=config.settings)==config
    assert after.settings['preserved']=='operator-setting' and legacy_anchor(after.settings)==ANCHOR
    assert verifier.confirm(source,'admin',meta['revision'],meta['discovery_id'],proof)==result
    with store.connect() as connection:
        assert connection.execute(sql.SQL("SELECT status FROM {} WHERE operation_kind='PLAN'").format(store.table('source_operations'))).fetchone()['status']=='STALE'
        assert connection.execute(sql.SQL('SELECT count(*) AS total FROM {}').format(store.table('source_identity_verifications'))).fetchone()['total']==1
    with pytest.raises(HostRegistrationConflict,match='HOST_ALREADY_REGISTERED'):
        HostReservations(registry._connect,registry.schema).check(preview())


def test_names_and_empty_inventory_cannot_prove_historical_identity(identity_fixture):
    store,registry,config,meta,proof=identity_fixture
    for changed in ({**proof,'owned':[]},{**proof,'host_uuid':str(uuid4())},
                    {**proof,'blockers':['HOST_OWNED_BY_OTHER_SOURCE']},
                    {**proof,'configured_target':{'site_slug':'other','cluster_name':config.target.cluster_name}}):
        with pytest.raises(LifecycleError,match='UNPROVED'):
            IdentityVerification(store).confirm(config.source_instance,'admin',meta['revision'],meta['discovery_id'],changed)
    assert registry.get_by_source_instance(config.source_instance).config==config


def test_new_discovery_and_other_source_identity_block_confirmation(identity_fixture):
    store,registry,config,meta,proof=identity_fixture
    other=replace(config,id='another-source',source_instance='another-source',settings={'onboarding_mapping':{'hosts':preview()['hosts']}})
    registry.create_source(other)
    with pytest.raises(LifecycleError,match='IDENTITY_CONFLICT'):
        IdentityVerification(store).confirm(config.source_instance,'admin',meta['revision'],meta['discovery_id'],proof)
    with store.connect() as connection:
        connection.execute(sql.SQL("UPDATE {} SET finished_at=clock_timestamp()-interval '11 minutes' WHERE operation_kind='DISCOVERY'").format(store.table('source_operations')))
    with pytest.raises(LifecycleError,match='DISCOVERY_REQUIRED'):
        IdentityVerification(store).describe(config.source_instance)


@pytest.mark.parametrize('status',['RUNNING','OUTCOME_UNCERTAIN','PARTIALLY_APPLIED'])
def test_unconfirmed_writes_prevent_identity_changes(identity_fixture,status):
    from netbox_sync.run_history import postgres_run_repository,RunTrigger,RunStatus
    store,registry,config,meta,proof=identity_fixture
    repository=postgres_run_repository(_safe_test_dsn(),store.schema)
    run=repository.start_run(config.source_instance,'esxi',RunTrigger.MANUAL,'fixture')
    if status!='RUNNING':repository.finish_run(run.run_id,RunStatus(status))
    with pytest.raises(LifecycleError,match='APPLY_UNCONFIRMED'):
        IdentityVerification(store).confirm(config.source_instance,'admin',meta['revision'],meta['discovery_id'],proof)
    assert legacy_anchor(registry.get_by_source_instance(config.source_instance).config.settings) is None


def test_verified_uuid_never_masks_a_different_recorded_uuid():
    proof={'provider':'esxi','version':1,'hardware_uuid':ANCHOR,'verification_id':str(uuid4())}
    assert legacy_anchor({'provider_identity':proof})==ANCHOR
    assert legacy_anchor({'provider_identity':proof,'onboarding_mapping':{'hosts':[{'id':'ha-host'}]}})==ANCHOR
    assert legacy_anchor({'provider_identity':proof,'onboarding_mapping':{'hosts':[{'id':str(uuid4())}]}}) is None


@pytest.mark.parametrize('change',['revision','discovery','recorded_uuid','running_operation'])
def test_confirmation_rechecks_generation_and_identity_under_lock(identity_fixture,change):
    store,registry,config,meta,proof=identity_fixture
    with store.connect() as connection:
        if change=='revision':
            connection.execute(sql.SQL('UPDATE {} SET name=%s WHERE source_instance=%s').format(store.table('sources')),('Renamed after review',config.source_instance))
        elif change=='discovery':
            connection.execute(sql.SQL("UPDATE {} SET operation_id=%s WHERE operation_kind='DISCOVERY'").format(store.table('source_operations')),(uuid4(),))
        elif change=='recorded_uuid':
            connection.execute(sql.SQL('UPDATE {} SET settings=%s WHERE source_instance=%s').format(store.table('sources')),
                (Jsonb({'onboarding_mapping':{'hosts':[{'id':str(uuid4())}]}}),config.source_instance))
        else:
            connection.execute(sql.SQL("INSERT INTO {} (source_instance,operation_kind,operation_id,status) VALUES (%s,'PLAN',%s,'RUNNING')").format(store.table('source_operations')),(config.source_instance,uuid4()))
    expected={'recorded_uuid':'IDENTITY_CHANGED','running_operation':'OPERATION_ACTIVE'}.get(change,'LIFECYCLE_CONFLICT')
    with pytest.raises(LifecycleError,match=expected):
        IdentityVerification(store).confirm(config.source_instance,'admin',meta['revision'],meta['discovery_id'],proof)
    with store.connect() as connection:
        assert connection.execute(sql.SQL('SELECT count(*) AS total FROM {}').format(store.table('source_identity_verifications'))).fetchone()['total']==0
