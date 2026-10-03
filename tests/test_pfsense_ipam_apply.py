from copy import deepcopy
from datetime import datetime, timezone
import pytest
from netbox_sync.pfsense_preview import build_preview
from netbox_sync.pfsense_ipam_apply import reviewed_addresses
from tests.test_pfsense_preview import sample

NOW=datetime(2026,10,3,19,0,tzinfo=timezone.utc)
EXPECTED={17:('bc:24:11:90:8c:32',['192.0.2.9/28','192.0.2.3/28'])}


def test_exact_reviewed_binding_and_all_ipv4_addresses():
    snapshot,inventory=sample()
    p=build_preview(snapshot,inventory,2609)
    assert reviewed_addresses(p,EXPECTED,NOW)==[(17,'192.0.2.3/28'),(17,'192.0.2.9/28')]


@pytest.mark.parametrize('change',['stale','future','mac','id','address','mask','missing','duplicate','unmatched'])
def test_any_changed_binding_blocks(change):
    snapshot,inventory=sample()
    p=build_preview(snapshot,inventory,2609)
    row=p['interfaces'][0]
    if change=='stale':p['collected_at']='2026-10-03T18:00:00Z'
    if change=='future':p['collected_at']='2026-10-03T20:00:00Z'
    if change=='mac':row['runtime']['mac']='bc:24:11:90:8c:34'
    if change=='id':row['match']['id']=18
    if change=='address':row['runtime']['addresses'][0]['address']='192.0.2.10/28'
    if change=='mask':row['runtime']['addresses'][0]['address']='192.0.2.9/32'
    if change=='missing':row['runtime']['addresses'].pop(0)
    if change=='duplicate':p['interfaces'].append(deepcopy(row))
    if change=='unmatched':p['unmatched_vm_interfaces']=[18]
    with pytest.raises(ValueError):reviewed_addresses(p,EXPECTED,NOW)
