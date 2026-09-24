"""Provider identity reservation gates; no credentials or live endpoints."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4
import pytest
from netbox_sync.host_registration import HostReservations, HostRegistrationConflict, esxi_anchor
from tests.test_migrations_postgres import migration_database, _upgrade
from tests.test_esxi_runtime import _config

ANCHOR = '503c5ad7-aaaa-bbbb-cccc-0123456789ab'

def preview(anchor=ANCHOR, name='host'):
    return {'provider':'esxi', 'hosts':[{'id':anchor, 'name':name}]}

@pytest.mark.parametrize('identifier', ['ha-host', '', None, '00000000-0000-0000-0000-000000000000'])
def test_local_provider_id_is_not_hardware_identity(identifier):
    with pytest.raises(HostRegistrationConflict, match='HOST_IDENTITY_UNAVAILABLE'):
        esxi_anchor(preview(identifier))

def test_names_and_transport_aliases_do_not_define_hardware_identity():
    for name in ('HOST.EXAMPLE.', 'host.example', 'alias.example', '192.0.2.20', 'different display name'):
        assert esxi_anchor(preview(ANCHOR.upper(), name)) == ANCHOR
    assert esxi_anchor(preview(str(uuid4()), 'host')) != esxi_anchor(preview(name='host'))

def test_reservation_is_atomic_and_survives_restart(migration_database):
    registry, engine = migration_database
    _upgrade(registry, engine)
    store = HostReservations(registry._connect, registry.schema)
    attempts = [('source-a',uuid4(),'actor-a'), ('source-b',uuid4(),'actor-b')]
    def attempt(args):
        try: return store.reserve(preview(), *args)
        except HostRegistrationConflict as error: return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, attempts))
    assert sorted(results) == sorted([ANCHOR, 'HOST_REGISTRATION_RESERVED'])
    winner = attempts[results.index(ANCHOR)]
    restarted = HostReservations(registry._connect, registry.schema)
    assert restarted.reserve(preview(name='renamed'), *winner) == ANCHOR
    with pytest.raises(HostRegistrationConflict, match='HOST_REGISTRATION_RESERVED'):
        restarted.check(preview())
    with pytest.raises(HostRegistrationConflict):
        restarted.reserve(preview(), winner[0], uuid4(), winner[2])
    assert not registry.list_sources()

def test_existing_and_removed_sources_retain_identity_without_name_matching(migration_database):
    registry, engine = migration_database
    _upgrade(registry, engine)
    config = replace(_config(), settings={'onboarding_mapping':{'hosts':preview()['hosts']}})
    registry.create_source(config)
    store = HostReservations(registry._connect, registry.schema)
    for check in (lambda: store.check(preview(name='another name')),
                  lambda: store.reserve(preview(), 'new-source', uuid4(), 'actor')):
        with pytest.raises(HostRegistrationConflict) as found: check()
        assert found.value.source_instance == config.source_instance
    from psycopg import sql
    with registry._connect() as connection:
        connection.execute(sql.SQL('INSERT INTO {} (source_instance,display_name,credential_state) VALUES (%s,%s,%s)').format(
            sql.Identifier(registry.schema,'source_tombstones')), (config.source_instance,config.name,'RETAINED_BY_REQUEST'))
    with pytest.raises(HostRegistrationConflict):
        store.reserve(preview(), 'new-source', uuid4(), 'actor')
    assert store.reserve(preview(str(uuid4()), 'same name'), 'different-host', uuid4(), 'actor')


def test_api_duplicate_refused_before_cluster_or_secret_side_effects(migration_database, monkeypatch):
    from fastapi.testclient import TestClient
    from netbox_sync.api.app import create_app
    from netbox_sync.api.auth import COOKIE
    from netbox_sync.api.settings import ApiSettings
    from netbox_sync.api.onboarding_adapters import RegistrationRegistry
    from netbox_sync.application.onboarding import EphemeralOnboardingStore, SourceOnboardingService
    from tests.test_onboarding import FakeSecrets, credentials, command
    from tests.test_directory_auth import configured
    from tests.test_operator_registration import HEADERS
    from dataclasses import asdict
    registry, engine = migration_database
    _upgrade(registry, engine)
    writer = RegistrationRegistry('unused',registry.schema)
    monkeypatch.setattr(writer, '_registry',lambda:registry)
    pending = EphemeralOnboardingStore()
    secret_store = FakeSecrets()
    service = SourceOnboardingService({},pending,writer,secret_store)
    policy, _, session = configured('operator')
    class Client:
        def call(self, action, **payload):return policy.call(dict(action=action,**payload))
    app = create_app(ApiSettings(bootstrap_socket=''), auth_client=Client(), onboarding_service=service)
    first_id = uuid4()
    HostReservations(registry._connect,registry.schema).reserve(preview(),'existing-attempt',first_id,'actor-first')
    # Simulate a probe issued before the competing request acquired its claim.
    token = pending.issue(credentials('esxi'),preview())
    policy.call(dict(action='receipt.issue',session=session,receipt=token,provider='esxi',destination='source.test',revision=0))
    payload=asdict(command(token,'esxi'))
    payload.pop('mapping',None)
    payload.update(registration_id=str(uuid4()),create_cluster=True,name='New host',cluster_name='New host',
                   references={},host_types={})
    import netbox_sync.api.catalog as catalog
    monkeypatch.setattr(catalog,'create_call',lambda *args:pytest.fail('Cluster write before identity reservation'))
    with TestClient(app,base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE,session)
        response=http.post('/api/v1/sources',headers=HEADERS,json=payload)
    assert response.status_code==409, response.text
    assert response.json()['error']['code']=='HOST_REGISTRATION_RESERVED'
    assert response.json()['error']['source_url'] is None
    assert response.json()['error']['existing_source'] is None
    assert not secret_store.values and not registry.list_sources()


def test_legacy_unknown_identity_cannot_be_bypassed_with_new_name(migration_database):
    registry, engine = migration_database
    _upgrade(registry, engine)
    registry.create_source(_config())
    store = HostReservations(registry._connect, registry.schema)
    with pytest.raises(HostRegistrationConflict, match='HOST_REGISTRY_REVIEW_REQUIRED'):
        store.reserve(preview(name='new name'), 'new-source', uuid4(), 'actor')


def test_existing_active_duplicates_cannot_pass_runtime_write_guard(migration_database):
    registry, engine = migration_database
    _upgrade(registry, engine)
    first = replace(_config(), settings={'onboarding_mapping':{'hosts':preview()['hosts']}})
    second = replace(first, id='other-source', source_instance='other-source', name='Another name', address='192.0.2.30')
    registry.create_source(first)
    registry.create_source(second)
    for config in (first,second):
        with pytest.raises(HostRegistrationConflict, match='HOST_IDENTITY_CONFLICT'):
            registry.assert_exclusive_host(config)
    assert len(registry.list_sources()) == 2


def test_final_api_concurrency_aliases_and_lost_response_do_not_duplicate(migration_database, monkeypatch):
    from dataclasses import asdict
    from threading import Lock
    from fastapi.testclient import TestClient
    from netbox_sync.api.app import create_app
    from netbox_sync.api.auth import COOKIE
    from netbox_sync.api.settings import ApiSettings
    from netbox_sync.api.onboarding_adapters import RegistrationRegistry
    from netbox_sync.application.onboarding import EphemeralOnboardingStore, SourceOnboardingService
    from tests.test_onboarding import FakeSecrets, credentials, command
    from tests.test_directory_auth import configured
    from tests.test_operator_registration import HEADERS
    registry, engine = migration_database
    _upgrade(registry, engine)
    writer = RegistrationRegistry('unused', registry.schema)
    monkeypatch.setattr(writer, '_registry', lambda: registry)
    pending, secrets = EphemeralOnboardingStore(), FakeSecrets()
    service = SourceOnboardingService({}, pending, writer, secrets)
    policy, _, session = configured('operator')
    auth_lock = Lock()
    class Client:
        def call(self, action, **payload):
            with auth_lock:
                return policy.call(dict(action=action, **payload))
    def mapping(*args, **kwargs):
        return {'hosts':preview()['hosts'], 'host_types':{ANCHOR:{'slug':'server'}},
                'references':{key:{'slug':value, 'name':'New source'} for key,value in
                    [('site','test'),('cluster','cluster'),('platform','platform'),
                     ('device_role','host'),('cluster_type','cluster')]}}
    monkeypatch.setattr('netbox_sync.api.catalog.validate', mapping)
    app = create_app(ApiSettings(bootstrap_socket=''), auth_client=Client(), onboarding_service=service)
    requests = []
    # Both probes completed before either final registration. The hardware proof,
    # not these independently bound transport addresses, defines the collision.
    for number, address in enumerate(('alias.example', '192.0.2.20')):
        token = pending.issue(credentials('esxi', address), preview())
        policy.call(dict(action='receipt.issue',session=session,receipt=token,
                         provider='esxi',destination=address,revision=0))
        payload = asdict(command(token,'esxi','candidate-'+str(number),address))
        payload.pop('mapping',None)
        payload['registration_id'] = str(uuid4())
        requests.append(payload)
    def post(payload):
        with TestClient(app,base_url='https://localhost:8000') as http:
            http.cookies.set(COOKIE,session)
            return http.post('/api/v1/sources',headers=HEADERS,json=payload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(post,requests))
    assert sorted(r.status_code for r in responses)==[201,409], [r.json() for r in responses]
    refused = next(r for r in responses if r.status_code==409).json()['error']
    assert refused['code'] in ('HOST_ALREADY_REGISTERED','HOST_REGISTRATION_RESERVED')
    winner = next(r.json()['source_instance'] for r in responses if r.status_code==201)
    assert refused['source_url']==('/sources/'+winner if refused['code']=='HOST_ALREADY_REGISTERED' else None)
    assert len(registry.list_sources())==1 and len(secrets.values)==1
    restarted = SourceOnboardingService({}, EphemeralOnboardingStore(), writer, FakeSecrets())
    restarted_app = create_app(ApiSettings(bootstrap_socket=''), auth_client=Client(), onboarding_service=restarted)
    monkeypatch.setattr('netbox_sync.api.catalog.create_call',
                        lambda *args: pytest.fail('Committed source does not require a catalog write or retry'))
    with TestClient(restarted_app,base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE,session)
        original = next(p for p in requests if p['source_instance']==winner)
        recovered = http.post('/api/v1/sources/registration-status',headers=HEADERS,json={
            'source_instance':winner,'registration_id':original['registration_id']})
        assert recovered.status_code==200, recovered.json()
        assert recovered.json()=={'status':'REGISTERED','identity_status':'REGISTERED',
                                  'source_instance':winner,'source_url':'/sources/'+winner}
    retry = post(next(p for p in requests if p['source_instance']==winner))
    assert retry.status_code==409
    assert len(registry.list_sources())==1 and len(secrets.values)==1


@pytest.mark.parametrize('address', ['host.example', 'HOST.EXAMPLE', 'host.example.',
                                    'alias.example', '192.0.2.20'])
def test_checked_probe_refuses_existing_uuid_for_every_transport_address(migration_database, monkeypatch, address):
    from netbox_sync.api.onboarding_adapters import RegistrationRegistry
    from netbox_sync.application.onboarding import EphemeralOnboardingStore, SourceOnboardingService
    from tests.test_onboarding import FakeSecrets, credentials
    registry, engine = migration_database
    _upgrade(registry, engine)
    existing = replace(_config(), settings={'onboarding_mapping':{'hosts':preview()['hosts']}})
    registry.create_source(existing)
    writer = RegistrationRegistry('unused', registry.schema)
    monkeypatch.setattr(writer, '_registry', lambda: registry)
    pending, secrets = EphemeralOnboardingStore(), FakeSecrets()
    monkeypatch.setattr(pending, 'issue', lambda *args: pytest.fail('Duplicate must not get a receipt'))
    service = SourceOnboardingService({}, pending, writer, secrets)
    # This boundary receives evidence only from the trusted probe, not from the
    # registration JSON. Network resolution is covered by production probe tests.
    with pytest.raises(HostRegistrationConflict) as failure:
        service.accept_checked_credentials(credentials('esxi', address), preview(name='Renamed'))
    assert failure.value.code == 'HOST_ALREADY_REGISTERED'
    assert failure.value.source_instance == existing.source_instance
    assert len(registry.list_sources()) == 1 and not secrets.values


def test_reconciliation_binds_actor_and_attempt_and_preserves_uncertainty(migration_database):
    from psycopg import sql
    registry, engine = migration_database
    _upgrade(registry, engine)
    store = HostReservations(registry._connect, registry.schema)
    config = replace(_config(), settings={'onboarding_mapping':{'hosts':preview()['hosts']}})
    attempt = uuid4()
    store.reserve(preview(), config.source_instance, attempt, 'owner')
    assert store.outcome(config.source_instance, attempt, 'another-operator') == {
        'identity_status':'NO_BOUND_ATTEMPT'}
    assert store.outcome(config.source_instance, uuid4(), 'owner') == {
        'identity_status':'NO_BOUND_ATTEMPT'}
    # Both before writes and after a lost credential/cluster response, no row is
    # not proof of no side effects. This read must never free the reservation.
    assert store.outcome(config.source_instance, attempt, 'owner') == {
        'identity_status':'OUTCOME_UNCERTAIN'}
    with pytest.raises(HostRegistrationConflict):
        store.reserve(preview(), 'other-source', uuid4(), 'owner')
    registry.create_source(config)
    assert store.outcome(config.source_instance, attempt, 'owner') == {
        'identity_status':'REGISTERED','source_instance':config.source_instance,
        'source_url':'/sources/'+config.source_instance}
    with registry._connect() as connection:
        connection.execute(sql.SQL('INSERT INTO {} (source_instance,display_name,credential_state) VALUES (%s,%s,%s)').format(
            sql.Identifier(registry.schema,'source_tombstones')),
            (config.source_instance,config.name,'REMOVED'))
    assert store.outcome(config.source_instance, attempt, 'owner') == {
        'identity_status':'RESTORE_REQUIRED'}
    with registry._connect() as connection:
        connection.execute(sql.SQL("UPDATE {} SET settings='{{}}' WHERE source_instance=%s").format(
            sql.Identifier(registry.schema,'sources')), (config.source_instance,))
    assert store.outcome(config.source_instance, attempt, 'owner') == {
        'identity_status':'IDENTITY_CONFLICT'}


def test_same_attempt_cannot_repeat_side_effects_concurrently(migration_database):
    registry,engine=migration_database;_upgrade(registry,engine)
    store=HostReservations(registry._connect,registry.schema)
    args=('source-a',uuid4(),'actor-a')
    store.reserve(preview(),*args)
    with store.registration_guard(preview(),*args):
        with pytest.raises(HostRegistrationConflict,match='HOST_REGISTRATION_RESERVED'):
            store.reserve(preview(),*args)
        with pytest.raises(HostRegistrationConflict,match='HOST_REGISTRATION_RESERVED'):
            with HostReservations(registry._connect,registry.schema).registration_guard(preview(),*args):
                pytest.fail('Concurrent request must not reach side effects')
    # Context exit releases only the lock, never the durable identity claim.
    with store.registration_guard(preview(),*args):pass
    with pytest.raises(HostRegistrationConflict,match='HOST_REGISTRATION_RESERVED'):
        store.reserve(preview(),'source-b',uuid4(),'actor-a')
    with pytest.raises(HostRegistrationConflict):
        with store.registration_guard(preview(),args[0],args[1],'another-actor'):pass


@pytest.mark.parametrize('role', ['viewer', 'operator', 'admin'])
def test_real_registration_conflict_distinguishes_tombstone_for_admin_only(migration_database, role):
    from fastapi.testclient import TestClient
    from netbox_sync.api.app import create_app
    from netbox_sync.api.settings import ApiSettings
    from netbox_sync.api.auth import COOKIE
    from netbox_sync.application.onboarding import SourceOnboardingService, EphemeralOnboardingStore
    from tests.test_onboarding import FakeRegistry, FakeSecrets
    from tests.test_directory_auth import configured
    from tests.test_operator_registration import HEADERS
    from psycopg import sql
    registry, engine = migration_database
    _upgrade(registry, engine)
    first = replace(_config(), settings={'onboarding_mapping': {'hosts':preview()['hosts']}})
    second = replace(first, id='removed-source', source_instance='removed-source')
    registry.create_source(first); registry.create_source(second)
    with registry._connect() as connection:
        connection.execute(sql.SQL('INSERT INTO {} (source_instance,display_name,credential_state) VALUES (%s,%s,%s)').format(
            sql.Identifier(registry.schema,'source_tombstones')), (second.source_instance,second.name,'RETAINED_BY_REQUEST'))
    store = HostReservations(registry._connect, registry.schema)
    secrets = FakeSecrets()
    onboarding = SourceOnboardingService({'esxi': lambda _: store.check(preview())},
                                         EphemeralOnboardingStore(), FakeRegistry(), secrets)
    auth, _, session = configured(role)
    class Client:
        def call(self, action, **payload): return auth.call(dict(action=action, **payload))
    app = create_app(ApiSettings(bootstrap_socket='', probe_socket=''), auth_client=Client(), onboarding_service=onboarding)
    with TestClient(app,base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE,session)
        response = http.post('/api/v1/sources/test-connection',headers=HEADERS,json={
            'source_type':'esxi','address':'source.test','username':'fixture','secret':'fixture', 'verify_ssl':True})
    assert response.status_code == (403 if role == 'viewer' else 409), response.text
    if role != 'viewer':
        error = response.json()['error']
        assert error['code'] == 'HOST_IDENTITY_CONFLICT'
        if role == 'admin':
            assert error['conflicts'] == [
                {'source_instance': first.source_instance, 'state':'REGISTERED'},
                {'source_instance': second.source_instance, 'state':'REMOVED'}]
        else: assert 'conflicts' not in error
    assert not secrets.values
    assert len(registry.list_sources()) == 2
