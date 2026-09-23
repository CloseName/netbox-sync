"""Actual PostgreSQL coordinator -> production worker -> real NetBox TLS gate."""
import json
import os
from pathlib import Path
from uuid import uuid4
from dataclasses import replace
import pytest
from tests.test_migrations_postgres import migration_database, _upgrade
from tests.test_source_registry_postgres import _safe_test_dsn
from tests.sample_data import sample_source_config
from netbox_sync.source_lifecycle import LifecycleStore
from netbox_sync.retirement_coordinator import RetirementCoordinator
from netbox_sync.retirement_worker import RetirementClient
from netbox_sync.local_control import ControlError
from netbox_sync.run_history import postgres_run_repository, RunStatus, RunTrigger

pytestmark=pytest.mark.skipif(os.environ.get('NETBOX_SYNC_GUARD_WORKER_TEST')!='1' or not Path('/.dockerenv').is_file(),
                             reason='isolated real NetBox/production Compose worker gate')


def test_real_netbox_receipt_before_tombstone(migration_database,tmp_path):
    meta=json.loads(Path('/bridge/ready.json').read_text())
    registry,engine=migration_database;_upgrade(registry,engine)
    source=replace(sample_source_config(),id=meta['source'],source_instance=meta['source'],source_type='esxi',legacy_identity_owner=False,
        settings={'onboarding_mapping':{'references':{'site':{'id':1},'cluster':{'id':meta['cluster']}}}})
    registry.create_source(source)
    store=LifecycleStore(_safe_test_dsn(),registry.schema,str(tmp_path/'apply.lock'))
    history=postgres_run_repository(_safe_test_dsn(),registry.schema)
    run=history.start_run(source.source_instance,'esxi',RunTrigger.MANUAL,'isolated-admin')
    history.finish_run(run.run_id,RunStatus.SUCCEEDED)
    service=RetirementCoordinator(store,RetirementClient('/worker/worker.sock'),lambda _:pytest.fail('no credential removal requested'))
    original=store.read(source.source_instance)
    review=service.review(source.source_instance,uuid4(),'isolated-admin',original['revision'])
    assert len(review['manifest']['objects'])==10 and review['guard_instance']==meta['guard_instance']
    assert store.read(source.source_instance)['removed_at'] is None
    original_call=service.remote.call
    def undelivered(action,operation,**values):
        if action=='execute':raise ControlError('RETIREMENT_UNCERTAIN')
        return original_call(action,operation,**values)
    service.remote.call=undelivered
    assert service.execute(source.source_instance,review['operation_id'],'isolated-admin',review['digest'],original['display_name'],False)['state']=='UNCERTAIN'
    service.remote.call=original_call
    # An ordinary retry reads the REAL NetBox REVIEWED receipt, never deletes.
    assert service.execute(source.source_instance,review['operation_id'],'isolated-admin',review['digest'],original['display_name'],False)['state']=='UNCERTAIN'
    assert store.read(source.source_instance)['removed_at'] is None
    restarted=RetirementCoordinator(store,RetirementClient('/worker/worker.sock'),lambda _:pytest.fail('no credential removal requested'))
    result=restarted.execute(source.source_instance,review['operation_id'],'isolated-admin',review['digest'],original['display_name'],False,resume=True)
    assert result['state']=='FINALIZED'
    assert store.read(source.source_instance)['retirement']['state']=='FINALIZED'
    assert not registry.get_by_source_instance(source.source_instance).config.enabled
    assert service.execute(source.source_instance,review['operation_id'],'isolated-admin',review['digest'],original['display_name'],False)==result
    assert history.get_run(run.run_id).status==RunStatus.SUCCEEDED
    Path('/bridge/done.json').write_text(json.dumps({'passed':True}))
