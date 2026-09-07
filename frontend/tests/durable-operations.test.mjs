import test from 'node:test';
import assert from 'node:assert/strict';
import {parseOperation,fetchOperations,startOperation,operationReason} from '../src/api/operations.ts';
import {sourceLifecycle} from '../src/api/lifecycle.ts';
const row={operation_id:'11111111-1111-4111-8111-111111111111',source_instance:'source-1',operation_kind:'PLAN',status:'RUNNING',started_at:'2026-09-07T00:00:00Z',updated_at:'2026-09-07T00:00:00Z',finished_at:null,safe_error_code:null,result:null};
test('operation parser rejects foreign identity and impossible result states',()=>{
  assert.equal(parseOperation(row,'source-1').operation_id,row.operation_id);
  for(const patch of [{source_instance:'source-2'},{status:'READY'},{status:'SUCCEEDED'},{result:{secret:'SENTINEL'}},{started_at:'not-time'}]) assert.throws(()=>parseOperation({...row,...patch},'source-1'));
});
test('operation client starts a protected source-bound resource and rejects duplicate slots',async(t)=>{
  let sent;
  t.mock.method(globalThis,'fetch',async(path,init)=>{sent={path,init};return new Response(JSON.stringify(row));});
  assert.equal((await startOperation('source-1','PLAN',new AbortController().signal)).operation_id,row.operation_id);
  assert.equal(sent.path,'/api/v1/sources/source-1/operations/plan');assert.equal(sent.init.headers['X-NetBox-Sync-CSRF'],'same-origin');assert.equal(sent.init.body,'{}');
  t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({operations:[row,row]})));
  await assert.rejects(fetchOperations('source-1',new AbortController().signal));
});
test('unknown operation and lifecycle failures never expose backend text',async(t)=>{
  assert.doesNotMatch(operationReason('SECRET_SENTINEL'),/SENTINEL/);
  t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({error:{code:'SECRET_SENTINEL',message:'SECRET_SENTINEL'}}),{status:500}));
  await assert.rejects(sourceLifecycle('source-1',new AbortController().signal),error=>!error.message.includes('SENTINEL'));
});
