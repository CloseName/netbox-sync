import test from 'node:test';
import assert from 'node:assert/strict';
import {parseOperation,fetchOperations,startOperation,operationReason,OperationRequestError,operationRequestMessage} from '../src/api/operations.ts';
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

test('operation state errors preserve confirmed categories and discard remote text',async(t)=>{
 const signal=new AbortController().signal;
 for(const [status,reason] of [[401,'ACCESS_DENIED'],[403,'ACCESS_DENIED'],[409,'HTTP_ERROR'],[503,'HTTP_ERROR']]){
  t.mock.method(globalThis,'fetch',async()=>new Response('REMOTE_SENTINEL',{status}));
  await assert.rejects(fetchOperations('source-1',signal),e=>e instanceof OperationRequestError&&e.reason===reason&&!e.message.includes('SENTINEL')&&!e.message.includes('connectivity'));
 }
 for(const [error,reason] of [[new TypeError('REMOTE_SENTINEL'),'TRANSPORT'],[new Error('REMOTE_SENTINEL'),'UNKNOWN']]){
  t.mock.method(globalThis,'fetch',async()=>{throw error;});
  await assert.rejects(fetchOperations('source-1',signal),e=>e.reason===reason&&!e.message.includes('SENTINEL'));
 }
 for(const body of ['not json',JSON.stringify({operations:[{...row,source_instance:'foreign'}]})]){
  t.mock.method(globalThis,'fetch',async()=>new Response(body));
  await assert.rejects(fetchOperations('source-1',signal),e=>e.reason==='INVALID_RESPONSE');
 }
 assert.doesNotMatch(operationRequestMessage(new Error('REMOTE_SENTINEL')),/SENTINEL|connectivity/);
});
test('timeout before headers and during response body is distinguished from malformed state',async(t)=>{
 for(const bodyStage of [false,true]){
  const controller=new AbortController();
  const fail=()=>{controller.abort(new DOMException('REMOTE_SENTINEL','TimeoutError'));throw controller.signal.reason;};
  t.mock.method(globalThis,'fetch',async()=>bodyStage?{ok:true,json:async()=>fail()}:fail());
  await assert.rejects(fetchOperations('source-1',controller.signal),e=>e.reason==='TIMEOUT'&&!e.message.includes('SENTINEL'));
 }
});
