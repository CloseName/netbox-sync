import test from 'node:test';
import assert from 'node:assert/strict';
import {readablePlanItem,planParent,changedObjectCount,filterPlan,emptyPlanLabel,planReason} from '../src/ui/plan.ts';
test('planned references display names while canonical data stays unchanged',()=>{
 const host={action:'CREATE',object_kind:'dcim.devices',external_id:'node-a',name:'NODE-A',matched_object_id:null,before:[],after:[['id',-1],['name','NODE-A']]};
 const nic={action:'CREATE',object_kind:'dcim.interfaces',external_id:'-1',name:'vmbr0',matched_object_id:null,before:[],after:[['id',-1],['device',-1],['name','vmbr0']]};
 const before=JSON.stringify([host,nic]);const result=readablePlanItem(nic,[host,nic]);
 assert.equal(new Map(result.after).get('device'),'NODE-A');assert.equal(result.external_id,'vmbr0');
 assert.equal(new Map(readablePlanItem({...nic,after:[['offset',-1]]},[host,nic]).after).get('offset'),-1);
 assert.equal(JSON.stringify([host,nic]),before);assert(!JSON.stringify(result).includes('-1'));
});

test('parent network grouping and unique target counts never change canonical operations',()=>{
 const host={action:'CREATE',object_kind:'dcim.devices',external_id:'node-a',name:'NODE-A',matched_object_id:null,before:[],after:[['id',-1],['name','NODE-A']]};
 const nic={action:'CREATE',object_kind:'dcim.interfaces',external_id:'-1',name:'eth0',matched_object_id:null,before:[],after:[['id',-1],['device',-1]]};
 const update={...nic,action:'UPDATE',matched_object_id:-1,after:[['description','managed']]};
 const mac={...nic,object_kind:'dcim.mac_addresses',after:[['id',-1],['assigned_object_type','dcim.interface'],['assigned_object_id',-1]]};
 const items=[host,nic,update,mac];assert.equal(changedObjectCount(items),3);assert.equal(planParent(mac,items),'NODE-A');
 const unsupported={...host,action:'UNSUPPORTED'};
 assert.equal(emptyPlanLabel([{...host,action:'NO_CHANGE'},unsupported]),'No changes to apply');
 assert.deepEqual(filterPlan([unsupported],'Attention','UNSUPPORTED','',''),[unsupported]);
});

test('structured reason takes priority over legacy mutation description',()=>{
 const reason='Existing guarded executor would perform this managed-field mutation.';
 assert.match(planReason({reason,reason_code:'ESXI_HOST_NETWORK_UNSUPPORTED',action:'UNSUPPORTED'}),/report-only/);
 assert.equal(planReason({reason,reason_code:'GUARDED_EXECUTOR_ACTION',action:'CREATE'}),'Create managed object');
});
