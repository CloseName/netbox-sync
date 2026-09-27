import test from 'node:test';
import assert from 'node:assert/strict';
import {readSourceDraft,saveSourceDraft} from '../src/ui/sourceDraft.ts';

test('drafts isolate accounts, whitelist fields and expire without storing credentials',()=>{
 const rows=new Map();
 globalThis.sessionStorage={getItem:k=>rows.get(k)??null,setItem:(k,v)=>rows.set(k,v),removeItem:k=>rows.delete(k)};
 const draft={type:'esxi',connection:{address:'host.example.test',port:8443,verify_ssl:false,secret:'must-not-persist'},name:'Draft',source_instance:'esxi-new',uncertain:false,password:'must-not-persist',onboarding_token:'must-not-persist'};
 saveSourceDraft('alice',draft);
 assert.equal(readSourceDraft('bob'),null);
 assert.equal(readSourceDraft('alice').connection.verify_ssl,false);
 assert.equal(readSourceDraft('alice').connection.port,8443);
 assert.ok(![...rows.values()].join('').includes('must-not-persist'));
 const key=[...rows.keys()][0],value=JSON.parse(rows.get(key));
 value.saved_at=Date.now()-9*3600000;rows.set(key,JSON.stringify(value));
 assert.equal(readSourceDraft('alice'),null);
 saveSourceDraft('alice',draft);saveSourceDraft('alice',null);
 assert.equal(rows.size,0);
 delete globalThis.sessionStorage;
});
