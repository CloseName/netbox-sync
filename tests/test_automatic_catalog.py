from types import SimpleNamespace as N
from urllib.parse import urlsplit, parse_qs

import pytest
from netbox_sync import automatic_catalog as m


def fixture(monkeypatch, status=201):
    rows=[]; calls=[]
    def fetch(session,url,token):
        assert token=='read'
        query=parse_qs(urlsplit(url).query)
        found=[r for endpoint,r in rows if endpoint==url.split('?')[0]
               and r.get('name',r.get('model'))==query.get('name',query.get('model'))[0]
               and ('manufacturer_id' not in query or str(r['manufacturer']['id'])==query['manufacturer_id'][0])]
        return {'count':len(found),'results':found,'next':None}
    def post(url,**kwargs):
        assert kwargs['allow_redirects'] is False
        assert 'apply' in kwargs['headers']['Authorization']
        calls.append((url,kwargs['json']))
        row={'id':len(rows)+1,**kwargs['json']}
        if 'manufacturer' in row: row['manufacturer']={'id':row['manufacturer'],'name':'Unknown'}
        if status in (201,400):rows.append((url,row))
        return N(status_code=status,json=lambda:row)
    monkeypatch.setattr(m,'fetch',fetch)
    issues=[]
    return m.ensure_factory(N(post=post),'https://netbox.test','read','apply',issues),calls,issues


@pytest.mark.parametrize('status',[201,400])
def test_repeated_or_concurrent_creation_reuses_exact_catalog(monkeypatch,status):
    ensure,calls,issues=fixture(monkeypatch,status)
    first=ensure('platform',{'name':'Proxmox VE'})
    second=ensure('platform',{'name':'Proxmox VE'})
    assert first==second and first['id']==1 and len(calls)==1 and not issues


def test_unknown_hardware_creates_manufacturer_and_model_only(monkeypatch):
    ensure,calls,issues=fixture(monkeypatch)
    value=ensure('device_type',{'manufacturer_name':'Unknown','model':'Hardware not identified'})
    assert value['manufacturer']['id']==1 and value['id']==2
    assert [url.rsplit('/',2)[1] for url,_ in calls]==['manufacturers','device-types']
    assert calls[1][1]['exclude_from_utilization'] is True
    assert not issues


def test_permissions_do_not_fall_back_to_another_token(monkeypatch):
    ensure,calls,issues=fixture(monkeypatch,403)
    assert ensure('platform',{'name':'Proxmox VE'}) is None
    assert len(calls)==1 and issues==[{'kind':'platform','code':'ADD_PERMISSION_REQUIRED'}]
    with pytest.raises(m.ProbeError):ensure('site',{'name':'Never create a site'})
