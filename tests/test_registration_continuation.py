"""Resumable registration: real PostgreSQL and Unix broker, no live systems."""
from dataclasses import replace
from uuid import uuid4
import os
import pytest
from netbox_sync.host_registration import HostReservations,HostRegistrationConflict
from netbox_sync.api.onboarding_adapters import RegistrationRegistry,BrokerSecretStore
from netbox_sync.application.onboarding import SourceOnboardingService,EphemeralOnboardingStore,RegistrationWriteError,OnboardingError
from tests.test_migrations_postgres import migration_database,_upgrade
from tests.test_host_registration import preview
from tests.test_onboarding import credentials,command
from tests.test_secret_broker_transport import start_broker


@pytest.fixture(autouse=True, params=['503c5ad7-aaaa-bbbb-cccc-0123456789ab', '00000000-0000-0000-0000-ac1f6be2c4da'])
def host_uuid_variant(request, monkeypatch):
    import tests.test_host_registration as registration
    monkeypatch.setattr(registration, 'ANCHOR', request.param)

def test_intent_is_immutable_and_resume_never_bypasses_actor_or_uuid(migration_database):
    registry,engine=migration_database;_upgrade(registry,engine)
    reservations=HostReservations(registry._connect,registry.schema)
    operation=uuid4();args=('source-a',operation,'owner')
    reservations.reserve(preview(),*args)
    resume={'source_instance':args[0],'registration_id':operation}
    reservations.check(preview(),resume=resume,actor_id='owner')
    for changed,actor in ((resume,'another-actor'),({**resume,'registration_id':uuid4()},'owner')):
        with pytest.raises(HostRegistrationConflict):
            reservations.check(preview(),resume=changed,actor_id=actor)
    with pytest.raises(HostRegistrationConflict):
        reservations.check(preview(str(uuid4())),resume=resume,actor_id='owner')
    first=reservations.bind_intent(preview(),*args,'a'*64)
    assert HostReservations(registry._connect,registry.schema).bind_intent(preview(),*args,'a'*64)==first
    with pytest.raises(HostRegistrationConflict,match='INTENT_CHANGED'):
        reservations.bind_intent(preview(),*args,'b'*64)
    assert not registry.list_sources()


@pytest.mark.skipif(not hasattr(os,'geteuid') or getattr(os,'geteuid',lambda:-1)()!=0,reason='Disposable Linux root broker required')
def test_registry_failure_then_restart_reuses_one_real_credential_file(migration_database,monkeypatch,tmp_path):
    registry,engine=migration_database;_upgrade(registry,engine)
    writer=RegistrationRegistry('unused',registry.schema)
    monkeypatch.setattr(writer,'_registry',lambda:registry)
    root=tmp_path/'secrets';root.mkdir(mode=0o700)
    socket=tmp_path/'broker.sock';broker=start_broker(root,socket)
    def service():return SourceOnboardingService({},EphemeralOnboardingStore(),writer,BrokerSecretStore(str(socket)))
    source='resumed-source';operation=uuid4();actor='operator-actor'
    attempt=service();token=attempt.accept_checked_credentials(credentials('esxi'),preview())
    request=command(token,'esxi',source)
    request=replace(request,mapping={'hosts':preview()['hosts']})
    attempt.reserve_provider_identity(request,operation,actor)
    actual_create=writer.create
    def refuse(_):raise RegistrationWriteError(definitely_failed=True)
    try:
        with attempt.registration_guard(request,operation,actor):
            intent=attempt.registration_intent(request,operation,actor,'a'*64)
            monkeypatch.setattr(writer,'create',refuse)
            with pytest.raises(OnboardingError,match='REGISTRATION_UNCERTAIN'):
                attempt.register(request,registration=intent)
        assert not registry.list_sources()
        assert [p.name for p in root.iterdir()]==[intent['credential_key']]
        assert (root/intent['credential_key']).stat().st_mode & 0o777==0o600
        # Process-local receipts/bookkeeping are gone. Fresh authenticated probe
        # evidence and the same actor/nonce are required to continue.
        restarted=service()
        receipt=restarted.accept_registration_resume(credentials('esxi'),preview(),source,operation,actor)
        resumed=replace(request,onboarding_token=receipt)
        with pytest.raises(OnboardingError):
            restarted.reserve_provider_identity(replace(resumed,source_instance='another-source'),operation,actor)
        restarted.reserve_provider_identity(resumed,operation,actor)
        def lost_commit_response(config):
            actual_create(config)
            raise RegistrationWriteError()
        monkeypatch.setattr(writer,'create',lost_commit_response)
        with restarted.registration_guard(resumed,operation,actor):
            same=restarted.registration_intent(resumed,operation,actor,'a'*64)
            result=restarted.register(resumed,registration=same)
        assert result.source_instance==source and not result.sync_enabled
        assert len(registry.list_sources())==1
        assert [p.name for p in root.iterdir()]==[intent['credential_key']]
        assert writer.registration_outcome(source,operation,actor)['identity_status']=='REGISTERED'
        with pytest.raises(HostRegistrationConflict,match='HOST_ALREADY_REGISTERED'):
            service().accept_registration_resume(credentials('esxi'),preview(),source,operation,actor)
    finally:
        broker.terminate();broker.wait(timeout=5)


def test_registration_intent_normalizes_transport_but_fences_target_and_metadata():
    from dataclasses import asdict
    from netbox_sync.api.onboarding_dto import RegistrationRequest
    payload=asdict(command('x'*32,'esxi','source-a','HOST.EXAMPLE.'));payload.pop('mapping')
    payload.update(registration_id=str(uuid4()),references={'site':{'id':1,'name':'Site'}},host_types={})
    first=RegistrationRequest(**payload)
    same=RegistrationRequest(**{**payload,'address':'host.example','port':443,
        'references':{'site':{'id':1,'name':'Renamed display label'}}})
    assert first.intent_fingerprint()==same.intent_fingerprint()
    for change in ({'name':'Different source'},{'references':{'site':{'id':2}}},{'port':8443}):
        assert RegistrationRequest(**{**payload,**change}).intent_fingerprint()!=first.intent_fingerprint()


def test_saved_request_survives_restart_is_actor_bound_and_never_contains_secrets(migration_database):
    from dataclasses import asdict
    from netbox_sync.api.onboarding_dto import RegistrationRequest
    registry,engine=migration_database;_upgrade(registry,engine)
    store=HostReservations(registry._connect,registry.schema)
    operation=uuid4();args=('source-a',operation,'owner')
    store.reserve(preview(),*args)
    payload=asdict(command('x'*32,'esxi','source-a'));payload.pop('mapping')
    payload.update(registration_id=str(operation),references={'site':{'id':1,'name':'ignored','extra_secret':'not-persisted'}},host_types={})
    request=RegistrationRequest(**payload)
    saved=request.durable_request()
    assert 'onboarding_token' not in saved and saved['references']=={'site':{'id':1}}
    store.bind_intent(preview(),*args,request.intent_fingerprint(),saved)
    restarted=HostReservations(registry._connect,registry.schema)
    assert restarted.pending_requests('other')==[]
    rows=restarted.pending_requests('owner')
    assert len(rows)==1 and rows[0]['request']==saved and rows[0]['registration_id']==str(operation)
    for extra in ({'secret':'must-not-save'},{'username':'must-not-save'},{'onboarding_token':'must-not-save'}):
        with pytest.raises((ValueError,HostRegistrationConflict)):
            store.bind_intent(preview(),*args,request.intent_fingerprint(),{**saved,**extra})
    assert restarted.pending_requests('owner')[0]['request']==saved


def test_legacy_placement_refusal_leaves_no_orphan_claim(migration_database,monkeypatch):
    from psycopg import sql
    from tests.test_esxi_runtime import _config
    registry,engine=migration_database;_upgrade(registry,engine)
    old=replace(_config(),enabled=False,settings={})
    registry.create_source(old)
    writer=RegistrationRegistry('unused',registry.schema)
    monkeypatch.setattr(writer,'_registry',lambda:registry)
    attempt=SourceOnboardingService({},EphemeralOnboardingStore(),writer,None)
    token=attempt.accept_checked_credentials(credentials('esxi'),preview())
    request=replace(command(token,'esxi','new-source'),site_slug=old.target.site_slug,cluster_name=old.target.cluster_name)
    operation=uuid4()
    with pytest.raises(HostRegistrationConflict,match='HOST_LEGACY_PLACEMENT_PROTECTED'):
        attempt.reserve_provider_identity(request,operation,'owner')
        with attempt.registration_guard(request,operation,'owner'):pass
    with registry._connect() as connection:
        count=connection.execute(sql.SQL('SELECT count(*) FROM {} WHERE source_instance=%s').format(sql.Identifier(registry.schema,'host_reservations')),('new-source',)).fetchone()['count']
    assert count==0, 'Placement refusal must not leave a claim without a recoverable intent'


def test_reservation_and_intent_commit_together_and_failure_rolls_back(migration_database,monkeypatch):
    from dataclasses import asdict
    from psycopg import sql
    from netbox_sync.api.onboarding_dto import RegistrationRequest
    registry,engine=migration_database;_upgrade(registry,engine)
    store=HostReservations(registry._connect,registry.schema)
    operation=uuid4()
    payload=asdict(command('x'*32,'esxi','atomic-source'));payload.pop('mapping')
    request=RegistrationRequest(**payload,registration_id=operation)
    intent={'fingerprint':request.intent_fingerprint(),'request':request.durable_request()}
    actual=store.bind_intent
    def failed(*a,**kw):
        actual(*a,**kw)
        raise RuntimeError('simulated interruption before commit')
    monkeypatch.setattr(store,'bind_intent',failed)
    with pytest.raises(RuntimeError):store.reserve(preview(),'atomic-source',operation,'owner',intent=intent)
    with registry._connect() as connection:
        for table in ('host_reservations','registration_intents'):
            assert connection.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(registry.schema,table))).fetchone()['count']==0
    monkeypatch.setattr(store,'bind_intent',actual)
    store.reserve(preview(),'atomic-source',operation,'owner',intent=intent)
    assert len(store.pending_requests('owner'))==1
    store.reserve(preview(),'atomic-source',operation,'owner',intent=intent)
    assert len(store.pending_requests('owner'))==1
    with pytest.raises(HostRegistrationConflict,match='INTENT_CHANGED'):
        store.reserve(preview(),'atomic-source',operation,'owner',intent={'fingerprint':'f'*64,'request':None})
    assert store.pending_requests('owner')[0]['request']==request.durable_request()
