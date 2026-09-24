import assert from 'node:assert/strict';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {buildSync} from 'esbuild';
const compiled=buildSync({entryPoints:[fileURLToPath(new URL('../src/api/retirement.ts',import.meta.url))],bundle:true,platform:'node',format:'esm',write:false}).outputFiles[0].text;
const {retirement,retainedContext,RetirementError}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const source='esxi-fixture',operation='a5b7ae0b-609a-46f0-bf92-103eaa087dd3';
const value={source_instance:source,operation_id:operation,state:'BLOCKED',digest:'a'.repeat(64),revision:'b'.repeat(64),guard_instance:operation,safe_code:'RETIREMENT_OWNERSHIP_UNPROVEN',manifest:{format:2,cluster_id:7,objects:[]}};
test('retirement preserves only a confirmed closed refusal and never retries',async ctx=>{
 let calls=0;ctx.mock.method(globalThis,'fetch',async()=>{calls++;return Response.json(value);});
 assert.equal((await retirement(source,'retire',{operation_id:operation},AbortSignal.timeout(1000))).safe_code,'RETIREMENT_OWNERSHIP_UNPROVEN');assert.equal(calls,1);
 ctx.mock.method(globalThis,'fetch',async()=>Response.json({...value,safe_code:'untrusted-secret'}));
 await assert.rejects(retirement(source,'retirement-status',{operation_id:operation},AbortSignal.timeout(1000)),error=>error instanceof RetirementError&&error.code==='RETIREMENT_UNAVAILABLE');
});
test('retained review context requests the Admin route with CSRF and validates exact source and revision',async ctx=>{
 ctx.mock.method(globalThis,'fetch',async(url,options)=>{
 assert.equal(url,`/api/v1/sources/${source}/retirement-context`);assert.equal(options.headers['X-NetBox-Sync-CSRF'],'same-origin');
 return Response.json({source_instance:source,display_name:'Retained',removed_at:'2026-09-24T00:00:00Z',revision:'b'.repeat(64),credential_state:'RETAINED_BY_REQUEST'});});
 assert.equal((await retainedContext(source,AbortSignal.timeout(1000))).display_name,'Retained');
 ctx.mock.method(globalThis,'fetch',async()=>Response.json({source_instance:'other',removed_at:null,revision:null}));
 await assert.rejects(retainedContext(source,AbortSignal.timeout(1000)),RetirementError);
});
