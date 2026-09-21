"""Exact automatic matching, including truthful generic hardware descriptions."""
import pytest
from netbox_sync.placement_resolution import resolve
from netbox_sync.netbox_catalog import project

def fixture(provider='esxi'):
    platform='VMware ESXi' if provider=='esxi' else 'Proxmox VE'
    rows={'site':[{'id':1,'name':'Configured site','slug':'configured'}],
          'platform':[{'id':2,'name':platform,'slug':'platform'}],
          'cluster_type':[{'id':3,'name':platform,'slug':'cluster-type'}],
          'device_role':[{'id':4,'name':'Hypervisor','slug':'hypervisor'}],
          'device_type':[{'id':5,'model':'Super Server','slug':'server','manufacturer':{'id':6,'name':'Supermicro'}}],
          'cluster':[]}
    payload={'provider':provider,'name':'Host A','hosts':[{'id':'uuid-a','model':'Super Server','manufacturer':'Supermicro'}]}
    def listing(kind,search):return {'results':rows[kind],'count':len(rows[kind]),'next':None}
    return rows,payload,listing

@pytest.mark.parametrize('provider',['esxi','proxmox'])
def test_unique_exact_generic_model_is_not_replaced_or_rejected(provider):
    rows,payload,listing=fixture(provider)
    result=resolve(payload,listing,project)
    assert not result['issues'] and result['create_cluster']
    assert result['host_types']['uuid-a']['name']=='Super Server'
    assert result['references']['site']['slug']=='configured'

@pytest.mark.parametrize('case',['missing','ambiguous','manufacturer','unknown','pagination'])
def test_incomplete_or_ambiguous_hardware_blocks(case):
    rows,payload,listing=fixture()
    if case=='missing':rows['device_type']=[]
    if case=='ambiguous':rows['device_type']*=2
    if case=='manufacturer':payload['hosts'][0]['manufacturer']='Other'
    if case=='unknown':payload['hosts'][0]['model']=None
    if case=='pagination':
        original=listing
        def listing(kind,search):return {**original(kind,search),'next':'more' if kind=='device_type' else None}
    result=resolve(payload,listing,project)
    assert 'uuid-a' not in result['host_types']
    assert any(i['kind']=='device_type' for i in result['issues'])

@pytest.mark.parametrize('case',['compatible','type','site','duplicate'])
def test_cluster_exact_name_scope_and_type(case):
    rows,payload,listing=fixture()
    rows['cluster']=[{'id':9,'name':'Host A','type':{'id':3},'scope_type':'dcim.site','scope_id':1}]
    if case=='type':rows['cluster'][0]['type']['id']=8
    if case=='site':rows['cluster'][0]['scope_id']=8
    if case=='duplicate':rows['cluster']*=2
    result=resolve(payload,listing,project)
    assert not result['create_cluster']
    assert bool(result['issues'])==(case!='compatible')
    assert ('cluster' in result['references'])==(case=='compatible')

def test_site_default_is_configuration_not_product_constant():
    rows,payload,listing=fixture();rows['site'].append({'id':7,'name':'Other','slug':'other'})
    assert 'site' not in resolve(payload,listing,project)['references']
    payload['default_site_slug']='other'
    assert resolve(payload,listing,project)['references']['site']['id']==7
    payload['site_id']=1
    assert resolve(payload,listing,project)['references']['site']['id']==1


def test_truncated_unpaginated_response_fails_closed():
    from netbox_sync.bootstrap_probe import ProbeError
    rows,payload,listing=fixture()
    def truncated(kind,search):return {**listing(kind,search),'count':2}
    with pytest.raises(ProbeError,match='RESPONSE_INVALID'):resolve(payload,truncated,project)
