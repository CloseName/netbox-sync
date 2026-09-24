"""Actual PostgreSQL legacy admission: quarantine is not identity/ownership proof."""
from dataclasses import replace
from uuid import uuid4
import pytest
from netbox_sync.legacy_admission import LegacyAdmission
from netbox_sync.source_lifecycle import LifecycleStore,LifecycleError
from netbox_sync.host_registration import HostReservations,HostRegistrationConflict,legacy_anchor,registration_anchor
from tests.test_migrations_postgres import migration_database,_upgrade
from tests.test_source_registry_postgres import _safe_test_dsn
from tests.test_esxi_runtime import _config
AM='00000000-0000-0000-0000-ac1f6be2c4da'
OLD='12345678-1234-4321-8765-123456789abc'

@pytest.fixture
def state(migration_database,tmp_path):
    registry,engine=migration_database;_upgrade(registry,engine)
    store=LifecycleStore(_safe_test_dsn(),registry.schema,str(tmp_path/'apply.lock'))
    return registry,store,LegacyAdmission(store),HostReservations(registry._connect,registry.schema)

def add(registry,source='legacy',enabled=True):
    config=replace(_config(),id=source,source_instance=source,name='ESXI-1L-SUP',enabled=enabled,settings={})
    registry.create_source(config);return config

def isolate(service,source,**overrides):
    request=dict(actor='admin',operation=uuid4(),revision=service.describe(source)['revision'],decision='ISOLATE',reason='Decommissioned, identity unavailable',anchor=None)
    request.update(overrides);return request,service.confirm(source,**request)

@pytest.mark.parametrize('state_name',['active','disabled','removed'])
def test_am_after_explicit_isolation_of_unrelated_unknown_record(state,state_name):
    registry,store,service,reservations=state;old=add(registry,enabled=state_name=='active')
    if state_name=='removed':
        view=store.read(old.source_instance);store.remove(old.source_instance,view['revision'],view['display_name'],False,lambda _:None)
    with pytest.raises(HostRegistrationConflict,match='HOST_REGISTRY_REVIEW_REQUIRED'):reservations.check({'provider':'esxi','hosts':[{'id':AM}]})
    request,result=isolate(service,old.source_instance)
    assert service.confirm(old.source_instance,**request)==result
    current=registry.get_by_source_instance(old.source_instance).config
    assert not current.enabled and not current.sync_enabled and legacy_anchor(current.settings) is None
    assert service.describe(old.source_instance)['isolated']
    reservations.reserve({'provider':'esxi','hosts':[{'id':AM}]},'am',uuid4(),'operator')
    with pytest.raises(HostRegistrationConflict):reservations.reserve({'provider':'esxi','hosts':[{'id':AM}]},'alias',uuid4(),'admin')
    if state_name=='removed':assert store.read(old.source_instance)['removed_at']
    assert service.status(old.source_instance,'admin',request['operation'])['proof']['decision']=='ISOLATE'
    assert service.status(old.source_instance,'other-admin',request['operation'])=={}


def test_all_unknown_records_require_separate_decisions(state):
    registry,store,service,reservations=state
    add(registry,'first');add(registry,'second');isolate(service,'first')
    with pytest.raises(HostRegistrationConflict) as error:reservations.check({'provider':'esxi','hosts':[{'id':AM}]})
    assert error.value.source_instance=='second'
    isolate(service,'second');reservations.check({'provider':'esxi','hosts':[{'id':AM}]})


def test_revision_and_nonce_fence_changed_record(state):
    registry,store,service,reservations=state;add(registry)
    request,result=isolate(service,'legacy')
    with pytest.raises(LifecycleError):service.confirm('legacy',**{**request,'actor':'other'})
    with pytest.raises(LifecycleError):service.confirm('legacy',**{**request,'operation':uuid4()})
    assert service.confirm('legacy',**request)==result


def test_observation_is_recorded_key_not_ownership_and_conflicting_claim_refuses(state):
    registry,store,service,reservations=state;add(registry)
    service.confirm('legacy','admin',uuid4(),service.describe('legacy')['revision'],'OBSERVE','Fresh separate old-server account',OLD)
    current=registry.get_by_source_instance('legacy').config
    assert legacy_anchor(current.settings) is None and 'provider_identity' not in current.settings
    assert registration_anchor(current.settings)==OLD
    assert not current.enabled and not current.sync_enabled
    assert current.settings['legacy_admission']['object_ownership_proved'] is False
    reservations.check({'provider':'esxi','hosts':[{'id':AM}]})
    with pytest.raises(HostRegistrationConflict,match='HOST_ALREADY_REGISTERED'):reservations.check({'provider':'esxi','hosts':[{'id':OLD}]})
    add(registry,'other')
    with pytest.raises(LifecycleError,match='SOURCE_IDENTITY_CONFLICT'):
        service.confirm('other','admin',uuid4(),service.describe('other')['revision'],'OBSERVE','Same observed UUID on another endpoint',OLD)


def test_final_guard_and_protected_placement(state,monkeypatch):
    from types import SimpleNamespace
    from netbox_sync.api.onboarding_adapters import RegistrationRegistry
    registry,store,service,reservations=state;old=add(registry)
    isolate(service,'legacy')
    preview={'provider':'esxi','hosts':[{'id':AM}]};operation=uuid4()
    reservations.reserve(preview,'am',operation,'operator')
    writer=RegistrationRegistry('unused',registry.schema);monkeypatch.setattr(writer,'_registry',lambda:registry)
    with reservations.registration_guard(preview,'am',operation,'operator'):
        writer.check_legacy_placement(SimpleNamespace(site_slug='new',cluster_name='AM'))
        with pytest.raises(HostRegistrationConflict,match='HOST_LEGACY_PLACEMENT_PROTECTED'):
            writer.check_legacy_placement(SimpleNamespace(site_slug=old.target.site_slug,cluster_name=old.target.cluster_name))
    with pytest.raises(HostRegistrationConflict,match='HOST_REGISTRY_REVIEW_REQUIRED'):
        registry.assert_exclusive_host(registry.get_by_source_instance('legacy').config)


def test_admission_serializes_against_registration_and_preserves_claim(state):
    from netbox_sync.legacy_admission import admission_lock
    from psycopg import sql
    registry,store,service,reservations=state;add(registry);isolate(service,'legacy')
    preview={'provider':'esxi','hosts':[{'id':AM}]};operation=uuid4()
    reservations.reserve(preview,'am',operation,'operator')
    with reservations.registration_guard(preview,'am',operation,'operator'):
        with pytest.raises(LifecycleError,match='SOURCE_LIFECYCLE_CONFLICT'):
            service.confirm('legacy','admin',uuid4(),service.describe('legacy')['revision'],'OBSERVE','Separate observation',OLD)
    with store.connect() as connection:
        admission_lock(connection,store.schema)
        with pytest.raises(HostRegistrationConflict,match='HOST_REGISTRATION_RESERVED'):
            reservations.reserve(preview,'am',operation,'operator')
    with pytest.raises(LifecycleError,match='SOURCE_IDENTITY_CONFLICT'):
        service.confirm('legacy','admin',uuid4(),service.describe('legacy')['revision'],'OBSERVE','UUID reserved by pending new source',AM)
    with store.connect() as connection:
        assert connection.execute(sql.SQL('SELECT count(*) AS total FROM {}').format(store.table('host_reservations'))).fetchone()['total']==1


@pytest.mark.parametrize('status',['RUNNING','OUTCOME_UNCERTAIN','PARTIALLY_APPLIED'])
def test_unconfirmed_writes_block_isolation(state,status):
    from netbox_sync.run_history import postgres_run_repository,RunTrigger,RunStatus
    registry,store,service,reservations=state;add(registry)
    repository=postgres_run_repository(_safe_test_dsn(),store.schema)
    run=repository.start_run('legacy','esxi',RunTrigger.MANUAL,'fixture')
    if status!='RUNNING':repository.finish_run(run.run_id,RunStatus(status))
    with pytest.raises(LifecycleError,match='SOURCE_APPLY_UNCONFIRMED'):isolate(service,'legacy')
    assert not service.describe('legacy')['isolated']


@pytest.mark.parametrize('role',['admin','operator','viewer'])
@pytest.mark.parametrize('removed',[False,True])
def test_api_legacy_roles_and_source_bound_probe(state,monkeypatch,role,removed):
    from fastapi.testclient import TestClient
    from netbox_sync.api.app import create_app
    from netbox_sync.api.settings import ApiSettings
    from netbox_sync.api.auth import COOKIE
    from netbox_sync.source_lifecycle import LifecycleError
    from netbox_sync.api.lifecycle_client import LifecycleRequestError
    from tests.test_directory_auth import configured
    from tests.test_operator_registration import HEADERS
    registry,store,legacy,reservations=state;old=add(registry)
    if removed:
        from psycopg import sql
        view=store.read('legacy');store.remove('legacy',view['revision'],view['display_name'],False,lambda _:pytest.fail('No credential access during fixture removal'))
        with store.connect() as connection:connection.execute(sql.SQL("UPDATE {} SET credential_state='REMOVED' WHERE source_instance='legacy'").format(store.table('source_tombstones')))
        assert legacy.describe('legacy')['state']=='REMOVED'
    auth,_,session=configured(role)
    class Auth:
        def call(self,action,**payload):return auth.call(dict(action=action,**payload))
    calls=[]
    def control(path,payload,**options):
        calls.append(payload['action']);action=payload['action'].removeprefix('legacy_')
        args={k:v for k,v in payload.items() if k not in {'action','source_instance'}}
        try:return {'result':getattr(legacy,action)(payload['source_instance'],**args)}
        except LifecycleError as exc:raise LifecycleRequestError(exc.code)
    monkeypatch.setattr('netbox_sync.local_control.request',control)
    secret=str(uuid4());probes=[]
    def probe(path,credentials,session,revision,preview):
        probes.append(credentials)
        assert credentials.address==old.address and credentials.secret==secret
        assert credentials.username=='separate-old-account'
        return {'provider':'esxi','hosts':[{'id':OLD}]}
    monkeypatch.setattr('netbox_sync.probe_worker.remote_test_authorized',probe)
    def client():
        return TestClient(create_app(ApiSettings(bootstrap_socket='',probe_socket='fixture'),auth_client=Auth()),base_url='https://localhost:8000')
    with client() as http:
        http.cookies.set(COOKIE,session)
        review=http.post('/api/v1/sources/legacy/legacy-review',json={},headers=HEADERS)
        if role!='admin':
            assert review.status_code==403
            for endpoint in ('probe','confirm'):
                assert http.post('/api/v1/sources/legacy/legacy-'+endpoint,json={},headers=HEADERS).status_code==403
            assert not calls and not probes;return
        assert review.status_code==200;revision=review.json()['revision']
        checked=http.post('/api/v1/sources/legacy/legacy-probe',json=dict(revision=revision,username='separate-old-account',secret=secret),headers=HEADERS)
        assert checked.status_code==200,checked.text
        assert secret not in checked.text and len(probes)==1
        payload=dict(operation=str(uuid4()),revision=revision,decision='OBSERVE',reason='Fresh separate old endpoint probe',evidence_token=checked.json()['evidence_token'],confirmed=True)
        reply=http.post('/api/v1/sources/legacy/legacy-confirm',json=payload,headers=HEADERS)
        assert reply.status_code==200,reply.text
    # Fresh API process loses the ephemeral evidence, durable same-actor retry still succeeds.
    with client() as restarted:
        restarted.cookies.set(COOKIE,session)
        assert restarted.post('/api/v1/sources/legacy/legacy-confirm',json=payload,headers=HEADERS).json()==reply.json()
    assert len(probes)==1
    assert secret not in str(legacy.status('legacy',auth.call(dict(action='authorize',session=session))['principal_id'],payload['operation']))


def test_pending_recovery_is_not_cancelled_by_legacy_decision(state):
    from psycopg import sql
    registry,store,service,reservations=state;add(registry)
    with store.connect() as connection:
        connection.execute(sql.SQL("INSERT INTO {} (operation_id,source_instance,actor_id,revision,plan,state) VALUES (%s,'legacy','admin','old','{{}}','CREDENTIALS_PENDING')").format(store.table('source_recoveries')),(uuid4(),))
    with pytest.raises(LifecycleError,match='SOURCE_RECOVERY_ACTIVE'):isolate(service,'legacy')
    assert not service.describe('legacy')['isolated']


def test_concurrent_decisions_have_one_winner_and_old_plan_is_stale(state):
    from concurrent.futures import ThreadPoolExecutor
    from psycopg import sql
    registry,store,service,reservations=state;add(registry)
    revision=service.describe('legacy')['revision']
    with store.connect() as connection:
        connection.execute(sql.SQL("INSERT INTO {} (source_instance,operation_kind,operation_id,status,result) VALUES ('legacy','PLAN',%s,'READY','{{}}')").format(store.table('source_operations')),(uuid4(),))
    def decide(_):
        try:return service.confirm('legacy','admin',uuid4(),revision,'ISOLATE','Reviewed unavailable endpoint')['status']
        except LifecycleError:return 'REFUSED'
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(decide,range(2)))==['RECORDED','REFUSED']
    with store.connect() as connection:
        assert connection.execute(sql.SQL("SELECT status FROM {} WHERE source_instance='legacy'").format(store.table('source_operations'))).fetchone()['status']=='STALE'
        assert connection.execute(sql.SQL('SELECT count(*) AS total FROM {}').format(store.table('source_identity_verifications'))).fetchone()['total']==1


def test_row_change_after_probe_refuses_without_audit(state):
    from psycopg import sql
    registry,store,service,reservations=state;add(registry)
    old_revision=service.describe('legacy')['revision']
    with store.connect() as connection:connection.execute(sql.SQL("UPDATE {} SET address='replacement.example.test' WHERE source_instance='legacy'").format(store.table('sources')))
    with pytest.raises(LifecycleError,match='SOURCE_LIFECYCLE_CONFLICT'):
        service.confirm('legacy','admin',uuid4(),old_revision,'OBSERVE','Old endpoint changed',OLD)
    assert service.describe('legacy')['host_uuid'] is None
    with store.connect() as connection:assert connection.execute(sql.SQL('SELECT count(*) AS total FROM {}').format(store.table('source_identity_verifications'))).fetchone()['total']==0
