import assert from 'node:assert/strict';
import test from 'node:test';
import {updateTokenUser} from '../src/ui/proxmoxToken.ts';
const initial={user:'',token:'',edited:false,parsed:false};
test('suggestion uses actual realm and does not invent one',()=>{
 assert.equal(updateTokenUser(initial,'netbox-sync@pam').token,'netbox-sync');
 assert.equal(updateTokenUser(initial,'netbox-sync').token,'');
 assert.equal(updateTokenUser(initial,'netbox-sync').user,'netbox-sync');
});
test('manual token name survives user edits',()=>{
 assert.equal(updateTokenUser({...initial,token:'inventory-reader',edited:true},'other@custom').token,'inventory-reader');
});
test('pasted full identifier explicitly supplies both fields',()=>{
 assert.deepEqual(updateTokenUser(initial,'netbox-sync@custom!inventory-reader'),{user:'netbox-sync@custom',token:'inventory-reader',edited:true,parsed:true});
});
test('invalid full identifiers remain visible without guessed splitting',()=>{
 for(const value of ['user!token','user@realm!','user@realm!a!b'])assert.equal(updateTokenUser(initial,value).user,value);
});
