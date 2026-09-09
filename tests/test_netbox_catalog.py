"""Bounded read-only references and server-side revalidation."""
from contextlib import nullcontext
from types import SimpleNamespace as N
from dataclasses import replace
import pytest
from netbox_sync import netbox_catalog as catalog
from netbox_sync.api.catalog import validate,CatalogError
from netbox_sync.host_mapping import validate as validate_runtime,device_types,cluster_filter


def row(kind,identifier=1,name='Example'):
    return catalog.project(kind,dict(id=identifier,name=name,model=name,slug='example',manufacturer={'id':9,'name':'Vendor'},type={'id':1,'name':'Example'},scope_type='dcim.site',scope_id=1))

@pytest.mark.parametrize('count,rows,more',[(0,[],False),(2000,[{'id':1,'name':'A','slug':'a'}],True),(2,[{'id':1,'name':'Same','slug':'a'},{'id':2,'name':'Same','slug':'b'}],False)])
def test_catalog_pagination_and_no_remote_next_follow(monkeypatch,count,rows,more):
    seen=[]
    monkeypatch.setattr(catalog,'EgressPolicy',lambda **kw:N(resolve=lambda h,p:(h,'192.0.2.1')))
    monkeypatch.setattr(catalog,'pinned_dns',lambda *a:nullcontext())
    monkeypatch.setattr(catalog,'configure_session',lambda s:None)
    def fetch(session,url,token):
        seen.append(url);return dict(results=rows,count=count,next='https://foreign.invalid/' if more else None)
    monkeypatch.setattr(catalog,'fetch',fetch)
    result=catalog.query(dict(url='https://netbox.test',read_token='',query=dict(action='list',kind='site',search='A & B',offset=20)),lambda:nullcontext(N()))
    assert result['count']==count and result['more']==more and len(seen)==1
    assert 'limit=20' in seen[0] and 'offset=20' in seen[0] and 'q=A+%26+B' in seen[0]
    assert all('url' not in r for r in result['items'])

@pytest.mark.parametrize('query',[dict(action='list',kind='devices'),dict(action='list',kind='site',offset=-1),dict(action='list',kind='site',search='x'*101)])
def test_invalid_query_no_http(monkeypatch,query):
    monkeypatch.setattr(catalog,'EgressPolicy',lambda **kw:N(resolve=lambda h,p:(h,'192.0.2.1')))
    monkeypatch.setattr(catalog,'pinned_dns',lambda *a:nullcontext())
    monkeypatch.setattr(catalog,'configure_session',lambda s:None)
    monkeypatch.setattr(catalog,'fetch',lambda *a:pytest.fail('No HTTP'))
    with pytest.raises(catalog.ProbeError):catalog.query(dict(url='https://netbox.test',read_token='',query=query),lambda:nullcontext(N()))


def test_changed_selection_refuses_before_registration(monkeypatch):
    import netbox_sync.api.catalog as gateway
    refs={kind:row(kind) for kind in ('site','cluster','platform','device_role','cluster_type')}
    host_types={'host-a':row('device_type')}
    monkeypatch.setattr(gateway,'call',lambda *args:(_ for _ in ()).throw(CatalogError('CATALOG_CHANGED')))
    with pytest.raises(CatalogError):validate('/socket',refs,host_types,{'hosts':[{'id':'host-a'}]})
    with pytest.raises(CatalogError):validate('/socket',refs,host_types,{'hosts':[{'id':'host-b'}]})


def test_two_hosts_never_share_source_default_and_unknown_hosts_fail():
    refs={kind:row(kind) for kind in ('site','cluster','platform','device_role','cluster_type')}
    types={'a':row('device_type',10,'Model A'),'b':row('device_type',11,'Model B')}
    mapping=dict(version=1,references=refs,host_types=types,hosts=[{'id':'a','manufacturer':None,'model':None},{'id':'b','manufacturer':None,'model':None}])
    def endpoint(kind):
        def get(id):
            choice=next(r for r in (list(types.values()) if kind=='device_type' else [refs[kind]]) if r['id']==id)
            return N(id=id,name=choice['name'],model=choice['name'],slug=choice['slug'],manufacturer=N(id=9),type=N(id=1),scope_type='dcim.site',scope_id=1)
        return N(get=get)
    api=N(dcim=N(sites=endpoint('site'),platforms=endpoint('platform'),device_roles=endpoint('device_role'),device_types=endpoint('device_type')),virtualization=N(clusters=endpoint('cluster'),cluster_types=endpoint('cluster_type')))
    config=N(onboarding_mapping=mapping,device_type_slug='must-not-use',cluster_name='Example')
    hosts=[N(source_id='a'),N(source_id='b')]
    validate_runtime(api,config,hosts)
    assert {k:r.id for k,r in device_types(api,config,hosts,None).items()}=={'a':10,'b':11}
    assert cluster_filter(config)=={'id':1}
    with pytest.raises(ValueError):validate_runtime(api,config,[N(source_id='new-host')])
    mapping['hosts'][0]['model']='Original'
    with pytest.raises(ValueError):validate_runtime(api,config,[N(source_id='a',model='Replacement')])


def test_api_revalidates_before_secret_or_registry_write_and_allows_explicit_retry(monkeypatch):
    from fastapi.testclient import TestClient
    from tests.auth_support import authenticated_app
    from tests.test_onboarding import service,credentials,command,HEADERS
    from netbox_sync.api.settings import ApiSettings
    import netbox_sync.api.catalog as gateway
    instance,registry,secrets=service()
    preview={'hosts':[{'id':'a','name':'Host A','model':None,'manufacturer':None}]}
    token=instance.accept_checked_credentials(credentials(),preview)
    refs={kind:row(kind) for kind in ('site','cluster','platform','device_role','cluster_type')}
    payload={k:v for k,v in command(token).__dict__.items() if k!='mapping'}
    payload.update(references=refs,host_types={'a':row('device_type')})
    changed=True
    def revalidate(_path,query):
        if changed:raise CatalogError('CATALOG_CHANGED')
        return {'selections':[dict(kind=c['kind'],**row(c['kind'])) for c in query['selections']]}
    monkeypatch.setattr(gateway,'call',revalidate)
    with TestClient(authenticated_app(ApiSettings(allowed_write_hosts=('testserver',)),onboarding_service=instance)) as client:
        rejected=client.post('/api/v1/sources',json=payload,headers=HEADERS)
        assert rejected.status_code==409 and rejected.json()['error']['code']=='CATALOG_CHANGED'
        assert not registry.records and not secrets.values and instance.preview(token)==preview
        changed=False
        response=client.post('/api/v1/sources',json=payload,headers=HEADERS)
        assert response.status_code==201
        saved=registry.records['new-source']
        assert not saved.sync_enabled and saved.settings['onboarding_mapping']['host_types']['a']['id']==1
        assert saved.target.onboarding_mapping==saved.settings['onboarding_mapping']
        assert saved.target.site_slug=='example'
