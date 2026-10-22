import test from 'node:test';
import assert from 'node:assert/strict';
import {observationRefreshOnly,changedObjectCount,filterPlan,hasChanges,planCounts} from '../src/ui/plan.ts';

function item(source='esxi') {
 const fields={hardware_identity:{version:1,source,status:'collected',observed_at:'2026-10-22T10:00:00Z',identifiers:[],conflicts:[]},operator:'keep'};
 return {action:'UPDATE',object_kind:'dcim.devices',external_id:'1',matched_object_id:1,name:'HOST',reason:'',reason_code:'MANAGED_FIELD_UPDATE',before:[['custom_fields',fields]],after:[['custom_fields',{...fields,hardware_identity:{...fields.hardware_identity,observed_at:'<fresh-collection-time>'}}]]};
}
test('clock-only rows cannot enable manual sync but stay in the canonical plan',()=>{
 for(const source of ['esxi','proxmox']) {
  const row=item(source), original=JSON.stringify(row);
  assert.equal(observationRefreshOnly(row),true);
  assert.equal(changedObjectCount([row]),0);
  assert.equal(planCounts([row]).UPDATE,1);
  assert.equal(hasChanges([row]),false);
  assert.deepEqual(filterPlan([row],'Changes','','',''),[]);
  assert.deepEqual(filterPlan([row],'Observation time','','',''),[row]);
  assert.deepEqual(filterPlan([row],'All','UPDATE','',''),[row]);
  assert.equal(JSON.stringify(row),original);
 }
});
test('real changes, incomplete evidence and other timestamps are never hidden',()=>{
 const changes=[
  r=>{r.after[0][1].hardware_identity.status='read_error'},
  r=>{r.after[0][1].hardware_identity.identifiers=[{value:'new'}]},
  r=>{r.after[0][1].operator='changed'},
  r=>{r.after.push(['name','NEW'])},
  r=>{r.before=[]},
  r=>{delete r.before[0][1].hardware_identity.observed_at},
  r=>{r.after[0][1].hardware_identity.source='selectel'},
  r=>{r.object_kind='virtualization.virtual_machines'},
  r=>{r.action='CREATE'},
  r=>{r.after[0][1].hardware_identity.observed_at=r.before[0][1].hardware_identity.observed_at},
 ];
 for(const change of changes){const row=item();change(row);assert.equal(observationRefreshOnly(row),false);assert.equal(changedObjectCount([row]),1);}
});
test('mixed operations on the same device still count the substantive change',()=>{
 const refresh=item(), real=structuredClone(refresh);real.after.push(['name','NEW']);
 assert.equal(changedObjectCount([refresh,real]),1);
 assert.equal(hasChanges([refresh,real]),true);
 assert.equal(hasChanges([]),false);
 assert.deepEqual(filterPlan([refresh,real],'Changes','','',''),[real]);
});
