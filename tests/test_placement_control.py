"""Real PostgreSQL placement fences; no provider/NetBox connectivity."""
from uuid import uuid4
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest
from tests.test_source_lifecycle_postgres import lifecycle
from tests.test_migrations_postgres import migration_database
from netbox_sync import placement_control as control
from netbox_sync.source_lifecycle import LifecycleError
from netbox_sync.netbox_catalog import project


def seed(store,source):
    identifier=str(uuid4())
    hosts=[dict(id='host-a',name='Node',memory_bytes=0)]
    with store.connect() as connection:
        connection.execute(sql.SQL("INSERT INTO {} (source_instance,operation_kind,operation_id,status,result,finished_at) VALUES (%s,'DISCOVERY',%s,'SUCCEEDED',%s,clock_timestamp())").format(store.table('source_operations')),(source,identifier,Jsonb({'hosts':hosts})))
    view=control.read(store,source)
    refs={k:project(k,dict(id=i+1,name=k,slug=k)) for i,k in enumerate(sorted(control.KINDS))}
    refs['cluster']=project('cluster',dict(id=12,name='Cluster',scope_type='dcim.site',scope_id=refs['site']['id'],type={'id':refs['cluster_type']['id'],'name':'cluster_type'}))
    mapping=dict(version=1,references=refs,host_types={'host-a':project('device_type',dict(id=13,model='Server',slug='server'))},hosts=view['preview']['hosts'])
    return view,mapping


def test_mapping_update_preserves_identity_and_invalidates_plan(lifecycle):
    store,registry,source=lifecycle
    view,mapping=seed(store,source.source_instance)
    before=registry.get_by_source_instance(source.source_instance).config
    with store.connect() as connection:
        connection.execute(sql.SQL("INSERT INTO {} (source_instance,operation_kind,operation_id,status,result) VALUES (%s,'PLAN',%s,'READY','{{}}')").format(store.table('source_operations')),(source.source_instance,str(uuid4())))
    control.save(store,source.source_instance,view['revision'],view['discovery_id'],mapping)
    after=registry.get_by_source_instance(source.source_instance).config
    assert after.credentials==before.credentials and after.address==before.address and after.name==before.name
    assert after.sync_enabled==before.sync_enabled
    with store.connect() as connection:
        row=connection.execute(sql.SQL("SELECT status,result FROM {} WHERE operation_kind='PLAN'").format(store.table('source_operations'))).fetchone()
        assert row['status']=='STALE' and row['result'] is None
    with pytest.raises(LifecycleError,match='SOURCE_LIFECYCLE_CONFLICT'):
        control.save(store,source.source_instance,view['revision'],view['discovery_id'],mapping)


def test_requires_discovery_and_blocks_active_plan(lifecycle):
    store,registry,source=lifecycle
    with pytest.raises(LifecycleError,match='SOURCE_DISCOVERY_REQUIRED'):control.read(store,source.source_instance)
    view,mapping=seed(store,source.source_instance)
    with store.connect() as connection:
        connection.execute(sql.SQL("INSERT INTO {} (source_instance,operation_kind,operation_id,status) VALUES (%s,'PLAN',%s,'RUNNING')").format(store.table('source_operations')),(source.source_instance,str(uuid4())))
    with pytest.raises(LifecycleError,match='SOURCE_OPERATION_ACTIVE'):
        control.save(store,source.source_instance,view['revision'],view['discovery_id'],mapping)
    assert registry.get_by_source_instance(source.source_instance).config.settings=={}


def test_observation_policy_revision_preservation_and_plan_fencing(lifecycle):
    from netbox_sync.application.ip_observations import source_policy
    store,registry,source=lifecycle
    view,mapping=seed(store,source.source_instance)
    assert view['ip_conflict_policy']=='strict'
    mapping['ip_conflict_policy']='observe'
    control.save(store,source.source_instance,view['revision'],view['discovery_id'],mapping)
    assert source_policy(registry.get_by_source_instance(source.source_instance).config)=='observe'
    with pytest.raises(LifecycleError,match='SOURCE_LIFECYCLE_CONFLICT'):
        control.save(store,source.source_instance,view['revision'],view['discovery_id'],mapping)
    fresh=control.read(store,source.source_instance)
    assert fresh['ip_conflict_policy']=='observe'
    mapping.pop('ip_conflict_policy')
    control.save(store,source.source_instance,fresh['revision'],fresh['discovery_id'],mapping)
    assert source_policy(registry.get_by_source_instance(source.source_instance).config)=='observe'
    fresh=control.read(store,source.source_instance)
    mapping['ip_conflict_policy']='guess'
    with pytest.raises(LifecycleError,match='REQUEST_INVALID'):
        control.save(store,source.source_instance,fresh['revision'],fresh['discovery_id'],mapping)
