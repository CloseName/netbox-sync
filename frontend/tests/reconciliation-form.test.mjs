import assert from 'node:assert/strict';
import test from 'node:test';
import Module from 'node:module';
import {fileURLToPath} from 'node:url';
import React from 'react';
import {buildSync} from 'esbuild';
const filename=fileURLToPath(import.meta.url);
const compiled=buildSync({entryPoints:[fileURLToPath(new URL('../src/components/RunReconciliation.tsx',import.meta.url))],bundle:true,platform:'node',format:'cjs',write:false,external:['react','react/jsx-runtime','react-router-dom']}).outputFiles[0].text;
const mod=new Module(filename);mod.filename=filename;mod.paths=Module._nodeModulePaths(fileURLToPath(new URL('..',import.meta.url)));
const load=mod.require.bind(mod);mod.require=id=>id==='react-router-dom'?{Link:'a'}:load(id);mod._compile(compiled,filename);
function nodes(node){return Array.isArray(node)?node.flatMap(nodes):node&&typeof node==='object'?[node,...nodes(node.props?.children)]:[];}
function setup(ctx){
 const state=[],refs=[];let cursor=0,rc=0;
 ctx.mock.method(React,'useSyncExternalStore',()=> 'ru');
 ctx.mock.method(React,'useEffect',()=>{});
 ctx.mock.method(React,'useState',initial=>{const i=cursor++;if(!(i in state))state[i]=initial;return [state[i],v=>{state[i]=typeof v==='function'?v(state[i]):v;}];});
 ctx.mock.method(React,'useRef',v=>refs[rc++]??(refs[rc-1]={current:v}));
 return ()=>{cursor=rc=0;return nodes(mod.exports.RunReconciliation({source:'esxi-fixture',onSaved:()=>{}}));};
}
const settle=()=>new Promise(resolve=>setTimeout(resolve,0));
test('baseline requires all acknowledgements and sends only the reviewed digest; new review clears old confirmation',async ctx=>{
 const render=setup(ctx),calls=[];let accepted=false;
 const review={digest:'a'.repeat(64),runs:[{run_id:'run-1',status:'OUTCOME_UNCERTAIN',finished_at:'2026-09-24T00:00:00Z'}],decisions:[],inventory:{objects:[]}};
 ctx.mock.method(globalThis,'fetch',async(path,options)=>{calls.push({path,payload:JSON.parse(options.body),headers:options.headers});if(path.endsWith('-confirm')){accepted=true;return Response.json({status:'BASELINE_ACCEPTED'});}return Response.json(accepted?{...review,runs:[],decisions:[{operation_id:'decision',actor_id:'server-admin-id',created_at:'2026-09-24',valid:true,runs:['run-1']}]}:review);});
 render().find(n=>n.type==='button').props.onClick();await settle();
 let buttons=render().filter(n=>n.type==='button');assert.equal(buttons.at(-1).props.disabled,true);
 for(const checkbox of render().filter(n=>n.type==='input'))checkbox.props.onChange({target:{checked:true}});
 buttons=render().filter(n=>n.type==='button');assert.equal(buttons.at(-1).props.disabled,false);
 buttons.at(-1).props.onClick();await settle();
 assert.equal(calls[1].payload.digest,review.digest);
 assert.equal(calls[1].payload.old_writes_stopped,true);assert.equal(calls[1].payload.outcome_stays_unknown,true);assert.equal(calls[1].payload.fresh_plan_required,true);
 assert.ok(!('actor_id' in calls[1].payload));assert.equal(calls[1].headers['X-NetBox-Sync-CSRF'],'same-origin');
 assert.match(JSON.stringify(render()),/историческ/i);
 render().find(n=>n.type==='button').props.onClick();await settle();
 assert.ok(render().some(n=>n.type==='a'&&n.props.to==='/runs/run-1'));
 assert.equal(render().filter(n=>n.type==='input').length,0);
 assert.ok(!render().some(n=>n.type==='button'&&String(n.props.children).includes('разрешить новый')));
});

test('reconciliation explains confirmed refusals without exposing arbitrary remote text',()=>{
 for(const language of ['en','ru']) {
  const message=mod.exports.reconciliationFailure('RETIREMENT_PERMISSION_DENIED',language);
  assert.match(message,/NetBox/);assert.match(message,/guard/);
  assert.notEqual(message,mod.exports.reconciliationFailure('SOURCE_OPERATION_ACTIVE',language));
  assert.notEqual(message,mod.exports.reconciliationFailure('SOURCE_LIFECYCLE_CONFLICT',language));
  assert.ok(!mod.exports.reconciliationFailure('secret-exception-text',language).includes('secret-exception-text'));
 }
});

test('accepted baseline refreshes retained-source removal gates without reloading the page',ctx=>{
 const output=buildSync({entryPoints:[fileURLToPath(new URL('../src/pages/SourceLifecycle.tsx',import.meta.url))],bundle:true,platform:'node',format:'cjs',write:false,external:['react','react/jsx-runtime','react-router-dom']}).outputFiles[0].text;
 const page=new Module(filename);page.filename=filename;page.paths=mod.paths;page.require=mod.require;page._compile(output,filename);
 const values=[];let index=0;
 ctx.mock.method(React,'useSyncExternalStore',()=> 'ru');
 ctx.mock.method(React,'useContext',()=>({principal:{permissions:['source.remove']}}));
 ctx.mock.method(React,'useState',initial=>{const i=index++;if(!(i in values))values[i]=initial;return [values[i],v=>{values[i]=typeof v==='function'?v(values[i]):v;}];});
 const render=()=>{index=0;return nodes(page.exports.RemovedSource({value:{source_instance:'esxi-fixture',display_name:'fixture',removed_at:'2026-09-24T00:00:00Z',credential_state:'RETAINED_BY_REQUEST'}}));};
 const before=render(),panel=before.find(n=>n.props?.retained===true);
 assert.ok(panel);before.find(n=>typeof n.props?.onSaved==='function').props.onSaved();
 assert.notEqual(render().find(n=>n.props?.retained===true).key,panel.key);
});
