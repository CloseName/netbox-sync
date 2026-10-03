import hashlib
import json
from uuid import uuid4
import pytest
from netbox_sync.guard_candidates import envelope


def saved():
    value={'source_instance':'esxi-test','items':[
        {'object_kind':'virtualization.virtual_machines','action':'CREATE','external_id':'one','after':[['name','private'],['cluster',31]]},
        {'object_kind':'dcim.devices','action':'CREATE','external_id':'host','after':[]}]}
    value['digest']=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
    return value


def test_export_binds_run_digest_and_source_without_executing_anything():
    plan=saved();run=uuid4()
    value=envelope(plan,run,'esxi-test',plan['digest'])
    assert value['run_id']==str(run)
    assert value['candidates']==[{'external_id':'one','data':{'name':'private','cluster':31}}]


@pytest.mark.parametrize('change',['source','digest','body','absent'])
def test_export_never_substitutes_a_newer_plan(change):
    plan=saved();digest=plan['digest']
    if change=='source':plan['source_instance']='other'
    if change=='digest':plan['digest']='b'*64
    if change=='body':plan['items'][0]['after'][0][1]='changed'
    if change=='absent':plan=None
    with pytest.raises(ValueError):envelope(plan,uuid4(),'esxi-test',digest)
