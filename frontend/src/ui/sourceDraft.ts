// Per-account, per-tab non-secret draft. Never persist credentials or probe receipts.
export type SourceDraft={type:'esxi'|'proxmox';connection:{address:string;port:number;verify_ssl:boolean};name:string;source_instance:string;registration_id?:string;site_id?:number;uncertain:boolean};
const prefix='netbox-sync.source-draft.';
export function readSourceDraft(owner:string|undefined):SourceDraft|null{
 if(!owner)return null;
 try{const value=JSON.parse(sessionStorage.getItem(prefix+owner)??'null');
  if(!value||typeof value.saved_at!=='number'||Date.now()-value.saved_at>8*3600_000)return null;
  const v=value.draft;
  if(!v||!['esxi','proxmox'].includes(v.type)||typeof v.connection?.address!=='string'||v.connection.address.length>253||typeof v.connection.verify_ssl!=='boolean'||!Number.isInteger(v.connection.port)||v.connection.port<1||v.connection.port>65535||typeof v.name!=='string'||v.name.length>200||typeof v.source_instance!=='string'||v.source_instance.length>63)return null;
  return {type:v.type,connection:{address:v.connection.address,port:v.connection.port,verify_ssl:v.connection.verify_ssl},name:v.name,source_instance:v.source_instance,
    ...(typeof v.registration_id==='string'&&/^[a-f0-9-]{36}$/.test(v.registration_id)?{registration_id:v.registration_id}:{}),
    ...(Number.isInteger(v.site_id)&&v.site_id>0?{site_id:v.site_id}:{}),uncertain:v.uncertain===true};
 }catch{return null;}
}
export function saveSourceDraft(owner:string|undefined,draft:SourceDraft|null){
 if(!owner)return;
 try{if(draft===null)sessionStorage.removeItem(prefix+owner);else sessionStorage.setItem(prefix+owner,JSON.stringify({saved_at:Date.now(),draft:{type:draft.type,connection:{address:draft.connection.address,port:draft.connection.port,verify_ssl:draft.connection.verify_ssl},name:draft.name,source_instance:draft.source_instance,registration_id:draft.registration_id,site_id:draft.site_id,uncertain:draft.uncertain}}));}catch{/* Disabled storage does not prevent registration. */}
}
