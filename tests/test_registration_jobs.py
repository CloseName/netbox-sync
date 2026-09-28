"""Durable completion with real PostgreSQL and broker-owned filesystem evidence."""
from dataclasses import asdict
from uuid import uuid4
import base64
import json
import pytest
from psycopg import sql
from netbox_sync.registration_jobs import RegistrationJobs, RegistrationContinuation, verify_staged
from netbox_sync.api.onboarding_dto import RegistrationRequest
from netbox_sync.api.onboarding_adapters import RegistrationRegistry
from netbox_sync.application.onboarding import SourceOnboardingService, EphemeralOnboardingStore, SecretReceipt, OnboardingError
from netbox_sync.host_registration import HostRegistrationConflict
from netbox_sync.secret_broker import SecretBrokerStore
from tests.test_migrations_postgres import migration_database, _upgrade
from tests.test_onboarding import credentials, command
from tests.test_host_registration import preview


@pytest.fixture
def context(migration_database, monkeypatch, tmp_path):
    registry, engine = migration_database
    _upgrade(registry, engine)
    jobs = RegistrationJobs('unused', registry.schema)
    from psycopg.rows import dict_row
    def connect():
        value = registry._connect()
        value.row_factory = dict_row
        return value
    monkeypatch.setattr(jobs, 'connect', connect)
    writer = RegistrationRegistry('unused', registry.schema)
    monkeypatch.setattr(writer, '_registry', lambda:registry)
    broker = SecretBrokerStore(tmp_path)
    class Secrets:
        def create(self, key, value, *, operation_id):
            return SecretReceipt(key, broker.create(operation_id,key,base64.b64encode(value.encode()).decode()))
        def forget(self, receipts): pass
    class Lifecycle:
        def connect(self): return connect()
        def table(self, name): return sql.Identifier(registry.schema,name)
    class Proof:
        def verify_owned(self, key, operation): return broker.verify_owned(operation,key)
    base = SourceOnboardingService({}, EphemeralOnboardingStore(), writer, Secrets())
    def attest(job): return verify_staged(Lifecycle(), Proof(),job['source_instance'],str(job['operation_id']),job['actor_id'])['verified']
    return jobs, base, registry, attest


def payload(provider):
    value = asdict(command('x'*32,provider,'registration-job-test'))
    value.pop('mapping')
    return RegistrationRequest(**value,registration_id=uuid4())


@pytest.mark.parametrize('provider',['esxi','proxmox'])
def test_restart_without_ephemeral_credentials_completes_once(context, provider):
    jobs, base, registry, attest = context
    request = payload(provider)
    creds = credentials(provider)
    job = jobs.begin(request,'actor',preview(),creds.username)
    jobs.stage(job,creds,base._secrets)
    # The restarted service has no ephemeral onboarding token or secret values.
    calls=[]
    def complete(request, staged, actor):
        calls.append(actor)
        return staged.register(request.command())
    restarted=RegistrationContinuation(jobs,base,complete,attest)
    restarted()
    assert jobs.get(request.source_instance)['state']=='COMPLETED'
    assert len(registry.list_sources())==1
    config=registry.get_source_config(request.source_instance)
    assert not config.sync_enabled
    assert config.credentials.token_secret.key==job['payload']['references']['secret']
    with jobs.guard(request.source_instance):
        restarted.run(jobs.get(request.source_instance))
    assert calls==['actor'] and len(registry.list_sources())==1
    text=json.dumps(job['payload'])
    assert creds.secret not in text and creds.token_id not in text if creds.token_id else creds.secret not in text
    assert 'onboarding_token' not in job['payload']['request']


@pytest.mark.parametrize('provider',['esxi','proxmox'])
def test_lost_staging_response_is_attested_and_missing_file_never_posts(context, provider, monkeypatch):
    jobs,base,registry,attest=context
    request=payload(provider);creds=credentials(provider)
    job=jobs.begin(request,'actor',preview(),creds.username)
    calls=[]
    runner=RegistrationContinuation(jobs,base,lambda request,service,actor:calls.append(actor) or service.register(request.command()),attest)
    runner()
    assert calls==[] and registry.list_sources()==()
    mark=jobs.mark
    monkeypatch.setattr(jobs,'mark',lambda *args: (_ for _ in ()).throw(ConnectionError()))
    with pytest.raises(ConnectionError):jobs.stage(job,creds,base._secrets)
    monkeypatch.setattr(jobs,'mark',mark)
    assert jobs.get(request.source_instance)['state']=='STAGING'
    runner()
    assert calls==['actor'] and len(registry.list_sources())==1


def test_immutable_actor_request_and_concurrent_execution(context):
    jobs,base,registry,attest=context
    request=payload('esxi');creds=credentials('esxi')
    job=jobs.begin(request,'actor',preview(),creds.username)
    for actor,change in [('other',{}),('actor',{'name':'changed'})]:
        with pytest.raises(HostRegistrationConflict):
            jobs.begin(request.model_copy(update=change),actor,preview(),creds.username)
    with jobs.guard(request.source_instance):
        with pytest.raises(OnboardingError):
            with jobs.guard(request.source_instance):pass
    assert not registry.list_sources()


def test_lost_registry_commit_response_and_background_failure_are_bounded(context,monkeypatch,caplog):
    jobs,base,registry,attest=context
    request=payload('esxi');creds=credentials('esxi')
    job=jobs.begin(request,'actor',preview(),creds.username);jobs.stage(job,creds,base._secrets)
    create=base._registry.create
    def lost(config):
        create(config)
        raise RuntimeError('untrusted remote secret sentinel')
    monkeypatch.setattr(base._registry,'create',lost)
    runner=RegistrationContinuation(jobs,base,lambda request,service,actor:service.register(request.command()),attest)
    runner()
    assert jobs.get(request.source_instance)['state']=='COMPLETED'
    assert len(registry.list_sources())==1
    assert 'untrusted remote secret sentinel' not in caplog.text


@pytest.mark.parametrize('provider',['esxi','proxmox'])
@pytest.mark.parametrize('role',['operator','admin','viewer'])
def test_real_api_continues_after_restart_without_session(context,monkeypatch,provider,role):
    import time
    from fastapi.testclient import TestClient
    import netbox_sync.api.app as api
    import netbox_sync.api.catalog as catalog
    import netbox_sync.registration_jobs as module
    import netbox_sync.local_control as control
    from netbox_sync.api.settings import ApiSettings
    from netbox_sync.api.auth import COOKIE
    from tests.test_directory_auth import configured
    from tests.test_operator_registration import HEADERS
    from tests.test_netbox_catalog import row
    jobs,base,registry,attest=context
    from netbox_sync.api.bootstrap import BootstrapClient
    from types import SimpleNamespace
    monkeypatch.setattr(BootstrapClient,'call',lambda *a,**kw:SimpleNamespace(status='READY'))
    policy,_,session=configured(role)
    class Auth:
        def call(self,action,**kwargs):return policy.call(dict(action=action,**kwargs))
    monkeypatch.setattr(api,'SourceOnboardingService',lambda *a,**kw:base)
    monkeypatch.setattr(module,'RegistrationJobs',lambda *a:jobs)
    def transport(path,payload,**kw):
        if payload['action']=='namespace-check':
            return {'result':dict(source_instance=payload['source_instance'],closed=False)}
        assert payload['action']=='registration_credentials'
        return {'result':{'verified':attest(jobs.get(payload['source_instance']))}}
    monkeypatch.setattr(control,'request',transport)
    monkeypatch.setattr(catalog,'call',lambda path,query:{'selections':[dict(kind=c['kind'],**row(c['kind'])) for c in query['selections']]})
    proof=preview();proof['provider']=provider
    token=base.accept_checked_credentials(credentials(provider),proof)
    if role!='viewer':
        policy.call(dict(action='receipt.issue',session=session,receipt=token,provider=provider,destination='source.test',revision=0))
    request=payload(provider).model_copy(update={'onboarding_token':token,'name':'Example', 'cluster_name':'Example',
        'references':{k:row(k) for k in ('site','cluster','platform','device_role','cluster_type')},
        'host_types':{proof['hosts'][0]['id']:row('device_type')}})
    original=base._registry.create
    monkeypatch.setattr(base._registry,'create',lambda config:(_ for _ in ()).throw(ConnectionError('untrusted secret exception')))
    settings=ApiSettings(registration_dsn='fixture',registry_schema=registry.schema,bootstrap_socket='fixture',probe_socket='')
    with TestClient(api.create_app(settings=settings,auth_client=Auth()),base_url='https://localhost:8000') as http:
        http.cookies.set(COOKIE,session)
        result=http.post('/api/v1/sources',headers=HEADERS,json={**request.model_dump(mode='json'),'onboarding_token':token})
        if role=='viewer':
            assert result.status_code==403 and jobs.get(request.source_instance) is None
            return
        assert result.status_code in (409,503),result.text
        assert 'untrusted secret exception' not in result.text
        assert jobs.get(request.source_instance)['state']=='READY'
        assert not registry.list_sources()
    # Lost process/session: all pending secrets are gone, only durable refs survive.
    base._pending=EphemeralOnboardingStore()
    monkeypatch.setattr(base._registry,'create',original)
    with TestClient(api.create_app(settings=settings,auth_client=Auth()),base_url='https://localhost:8000'):
        deadline=time.monotonic()+12
        while jobs.get(request.source_instance)['state']!='COMPLETED' and time.monotonic()<deadline:
            time.sleep(.1)
        assert jobs.get(request.source_instance)['state']=='COMPLETED'
    assert len(registry.list_sources())==1


@pytest.mark.parametrize('provider',['esxi','proxmox'])
def test_staging_resume_is_exact_and_never_restores_another_host(context,provider):
    from dataclasses import replace
    jobs,base,registry,attest=context
    request=payload(provider);creds=credentials(provider);proof=preview()
    jobs.begin(request,'actor',proof,creds.username)
    resumed=jobs.resume_staging(request.source_instance,request.registration_id,'actor',creds,proof)
    assert resumed['registration_resume']['source_instance']==request.source_instance
    for changed in (replace(creds,address='other.test'),replace(creds,port=8443),replace(creds,username='different')):
        with pytest.raises(HostRegistrationConflict):jobs.resume_staging(request.source_instance,request.registration_id,'actor',changed,proof)
    with pytest.raises(HostRegistrationConflict):
        jobs.resume_staging(request.source_instance,request.registration_id,'actor',creds,{**proof,'hosts':[]})
    jobs.mark(request.source_instance,'READY')
    with pytest.raises(HostRegistrationConflict):jobs.resume_staging(request.source_instance,request.registration_id,'actor',creds,proof)
    assert not registry.list_sources()
