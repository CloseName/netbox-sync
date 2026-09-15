import test from 'node:test';
import assert from 'node:assert/strict';
import {readablePlanItem} from '../src/ui/plan.ts';
test('planned references display names while canonical data stays unchanged',()=>{
 const host={action:'CREATE',object_kind:'dcim.devices',external_id:'node-a',name:'NODE-A',matched_object_id:null,before:[],after:[['id',-1],['name','NODE-A']]};
 const nic={action:'CREATE',object_kind:'dcim.interfaces',external_id:'-1',name:'vmbr0',matched_object_id:null,before:[],after:[['id',-1],['device',-1],['name','vmbr0']]};
 const before=JSON.stringify([host,nic]);const result=readablePlanItem(nic,[host,nic]);
 assert.equal(new Map(result.after).get('device'),'NODE-A');assert.equal(result.external_id,'vmbr0');
 assert.equal(new Map(readablePlanItem({...nic,after:[['offset',-1]]},[host,nic]).after).get('offset'),-1);
 assert.equal(JSON.stringify([host,nic]),before);assert(!JSON.stringify(result).includes('-1'));
});
