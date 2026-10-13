import test from 'node:test';
import assert from 'node:assert/strict';
import {attention,completedWithLimitations} from '../src/ui/operations.ts';
import {diagnostics} from './fixtures.mjs';
test('collection limitations stay neutral only with confirmed operation evidence',()=>{
 const s=diagnostics().sources[0];Object.assign(s,{status:'DEGRADED',operation_evidence_available:true,plan_blocked:false,outcome_unconfirmed:false});s.latest_run.unsupported_count=1;
 assert.equal(completedWithLimitations(s),true);assert.equal(attention(s),null);
 for(const change of [{plan_blocked:true},{outcome_unconfirmed:true},{operation_evidence_available:false},{warning_count:1},{warnings:['STALE_RUNNING']},{status:'UNAVAILABLE'}]){
  const unsafe={...s,...change};assert.equal(completedWithLimitations(unsafe),false);assert.ok(attention(unsafe));
 }
 for(const status of ['OUTCOME_UNCERTAIN','PARTIALLY_APPLIED','FAILED_BEFORE_WRITE','BLOCKED'])assert.ok(attention({...s,latest_run:{...s.latest_run,status}}));
});
