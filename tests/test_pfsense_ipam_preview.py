import pytest
from netbox_sync.pfsense_ipam_preview import classify, plan
from netbox_sync.pfsense_preview import build_preview
from tests.test_pfsense_preview import sample


def record(**kw):
    return dict(dict(id=1,address='192.0.2.9/28',vrf_id=None,assigned_type='virtualization.vminterface',assigned_id=17),**kw)


@pytest.mark.parametrize('records,selected,vrf,expected', [
    ([],False,None,'SCOPE_REQUIRED'),
    ([],True,None,'WOULD_CREATE_AND_ASSIGN'),
    ([record()],True,None,'ALREADY_ASSIGNED'),
    ([record(assigned_id=18)],True,None,'ASSIGNED_ELSEWHERE'),
    ([record(assigned_type='dcim.interface')],True,None,'ASSIGNED_ELSEWHERE'),
    ([record(assigned_type=None,assigned_id=None)],True,None,'UNASSIGNED_REVIEW_REQUIRED'),
    ([record(address='192.0.2.9/32')],True,None,'PREFIX_LENGTH_CONFLICT'),
    ([record(),record(id=2)],True,None,'DUPLICATE_IP_RECORDS'),
    ([record(vrf_id=5)],True,None,'WOULD_CREATE_AND_ASSIGN'),
    ([record(vrf_id=5)],True,5,'ALREADY_ASSIGNED'),
])
def test_classification(records,selected,vrf,expected):
    assert classify('192.0.2.9/28',17,records,selected,vrf)==expected


def test_network_and_broadcast_are_not_host_candidates():
    assert classify('192.0.2.0/24',17,[],True)=='INVALID_HOST_ADDRESS'
    assert classify('192.0.2.255/24',17,[],True)=='INVALID_HOST_ADDRESS'
    assert classify('192.0.2.0/31',17,[],True)=='WOULD_CREATE_AND_ASSIGN'


def test_plan_excludes_link_local_and_does_not_guess_scope_from_prefix():
    snapshot,inventory=sample()
    snapshot['configuration']['interfaces'][0]['name']='Arbitrary label'
    p=build_preview(snapshot,inventory,2609)
    facts={h:dict(addresses=[],prefixes=[dict(prefix='192.0.2.0/24',vrf_id=3)]) for h in ['192.0.2.9','192.0.2.3']}
    rows=plan(p,facts)
    assert len(rows)==2
    assert {r['action'] for r in rows}=={'SCOPE_REQUIRED'}
    assert {r['action'] for r in plan(p,facts,{'17':None})}=={'WOULD_CREATE_AND_ASSIGN'}
    with pytest.raises(ValueError):plan(p,facts,{'999':None})
    with pytest.raises(ValueError):plan(p,facts,{'17':True})


def test_duplicate_observation_blocks_and_foreign_evidence_rejected():
    snapshot,inventory=sample()
    p=build_preview(snapshot,inventory,2609)
    p['interfaces'][0]['runtime']['addresses']*=2
    facts={h:dict(addresses=[],prefixes=[]) for h in ['192.0.2.9','192.0.2.3']}
    assert {r['action'] for r in plan(p,facts,{'17':None})}=={'DUPLICATE_OBSERVATION'}
    facts['192.0.2.3']['addresses']=[record()]
    with pytest.raises(ValueError):plan(p,facts)
