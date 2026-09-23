"""Recovery evidence is a bounded read, never a capability to adopt or write."""
from copy import deepcopy
from contextlib import nullcontext
from types import SimpleNamespace
import pytest
from netbox_sync.recovery_evidence import assess
from netbox_sync.bootstrap_probe import ProbeError
from netbox_sync import netbox_catalog as catalog

UUID='503c5ad7-aaaa-bbbb-cccc-0123456789ab'
CLUSTER={'id':3,'scope_type':'dcim.site','scope_id':1}


def object_row(identifier=1,source='source-a',kind='host',external=UUID,cluster=3):
    return {'id':identifier,'name':'same display name','cluster':{'id':cluster},
            'custom_fields':{'sync_identities':[{'schema':'v2','type':'esxi',
                'instance':source,'kind':kind,'external_id':external}]}}


def report(devices, machines=(),cluster=CLUSTER):
    return assess('source-a',UUID,1,3,cluster,devices,list(machines))


def test_same_host_preserves_object_ids_and_manual_rows_without_name_adoption():
    manual={'id':2,'name':'same display name','cluster':{'id':3},'custom_fields':{}}
    before=deepcopy(manual)
    result=report([object_row()], [object_row(7,kind='vm',external='vm-uuid'),manual])
    assert not result['blockers']
    assert result['owned']==[{'kind':'device','id':1},{'kind':'vm','id':7}]
    assert result['retained_manual']==[{'kind':'vm','id':2}]
    assert manual==before
    assert report([])['owned']==[]  # Empty placement is not evidence of ownership.


@pytest.mark.parametrize('devices,code',[
    ([object_row(external='another-host')],'HOST_IDENTITY_MISMATCH'),
    ([object_row(source='another-source')],'HOST_OWNED_BY_OTHER_SOURCE'),
    ([object_row(),object_row(2)],'DUPLICATE_MANAGED_HOST'),
    ([object_row(cluster=9)],'OWNED_OBJECT_OUTSIDE_PLACEMENT'),
])
def test_ambiguity_never_selects_an_arbitrary_host(devices,code):
    assert code in report(devices)['blockers']


def test_scope_shared_ownership_and_legacy_are_explicit_blockers():
    shared=object_row()
    shared['custom_fields']['sync_identities']+=object_row(source='other')['custom_fields']['sync_identities']
    assert 'SHARED_OWNERSHIP' in report([shared])['blockers']
    assert 'PLACEMENT_CHANGED' in report([object_row()],cluster={**CLUSTER,'scope_id':2})['blockers']
    legacy=object_row();legacy['custom_fields']['sync_identities']=[{'source':'esxi','source_id':UUID}]
    assert 'LEGACY_OWNERSHIP_REVIEW_REQUIRED' in report([legacy])['blockers']


def test_digest_is_order_independent_but_includes_identity_changes():
    machines=[object_row(7,kind='vm',external='vm-a'),object_row(8,kind='vm',external='vm-b')]
    initial=report([object_row()],machines)
    assert report([object_row()],list(reversed(machines)))['digest']==initial['digest']
    machines[0]['custom_fields']['sync_identities'][0]['external_id']='changed'
    assert report([object_row()],machines)['digest']!=initial['digest']


@pytest.mark.parametrize('anchor',[None,'ha-host','00000000-0000-0000-0000-000000000000'])
def test_unknown_identity_fails_closed(anchor):
    with pytest.raises(ProbeError): assess('source-a',anchor,1,3,CLUSTER,[],[])


def test_catalog_reads_complete_pages_and_never_follows_remote_next(monkeypatch):
    monkeypatch.setattr(catalog,'EgressPolicy',lambda **kw:SimpleNamespace(resolve=lambda h,p:(h,'192.0.2.1')))
    monkeypatch.setattr(catalog,'pinned_dns',lambda *a:nullcontext())
    monkeypatch.setattr(catalog,'configure_session',lambda s:None)
    seen=[]
    def fetch(session,url,token):
        seen.append(url)
        if '/clusters/3/' in url:return CLUSTER
        if '/devices/' in url:return {'count':1,'next':None,'results':[object_row()]}
        if 'offset=0' in url:
            return {'count':101,'next':'https://untrusted.invalid/steal',
                    'results':[object_row(i+1,kind='vm',external=str(i+1)) for i in range(100)]}
        return {'count':101,'next':None,'results':[object_row(101,kind='vm',external='101')]}
    monkeypatch.setattr(catalog,'fetch',fetch)
    payload={'action':'recovery-evidence','source_instance':'source-a','host_uuid':UUID,'site_id':1,'cluster_id':3}
    result=catalog.query({'url':'https://netbox.test','read_token':'','query':payload},lambda:nullcontext(None))
    assert not result['blockers'] and len(result['owned'])==102
    assert len(seen)==4 and all(url.startswith('https://netbox.test/api/') for url in seen)
    def incomplete(session,url,token):
        if '/clusters/' in url:return CLUSTER
        return {'count':2,'next':None,'results':[object_row()]}
    monkeypatch.setattr(catalog,'fetch',incomplete)
    with pytest.raises(ProbeError):
        catalog.query({'url':'https://netbox.test','read_token':'','query':payload},lambda:nullcontext(None))


def test_repeated_identity_fact_is_not_another_object():
    host=object_row()
    host['custom_fields']['sync_identities']*=2
    assert report([host])==report([object_row()])


def test_distinct_objects_with_same_identity_block_recovery():
    machines=[object_row(7,kind='vm',external='vm-a'),object_row(8,kind='vm',external='vm-a')]
    assert 'DUPLICATE_OBJECT_IDENTITY' in report([object_row()],machines)['blockers']
    machines[1]['custom_fields']['sync_identities'][0]['external_id']='vm-b'
    assert not report([object_row()],machines)['blockers']


def test_wrong_kind_and_multiple_identities_on_one_owned_object_block():
    machine=object_row(7,kind='host',external=UUID)
    assert 'OBJECT_IDENTITY_CONFLICT' in report([object_row()],[machine])['blockers']
    machine=object_row(7,kind='vm',external='vm-a')
    machine['custom_fields']['sync_identities']+=object_row(7,kind='vm',external='vm-b')['custom_fields']['sync_identities']
    assert 'OBJECT_IDENTITY_CONFLICT' in report([object_row()],[machine])['blockers']
