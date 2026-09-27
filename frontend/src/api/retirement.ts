export type RetirementState = 'READY' | 'SENDING' | 'UNCERTAIN' | 'SUCCEEDED' | 'FINALIZED' | 'BLOCKED';
export interface Retirement {
  source_instance: string; operation_id: string; state: RetirementState; digest: string;
  revision: string; guard_instance: string; safe_code?: string | null; remove_credentials?: boolean | null;
  mode?: 'FULL_DELETE'|'LEGACY_RETAIN'; purged?: boolean;
  manifest: {format: 2|4; cluster_id?: number; retained?: {kind:string;id:number;present:boolean;claimed:boolean}[]; objects: [string,string][]; retained_cluster?: boolean};
}
export class RetirementError extends Error {
  constructor(readonly code: string) {super(code);}
}
const codes = new Set(['RETIREMENT_AUTH_FAILED','RETIREMENT_TOKEN_WRITE_REQUIRED','RETIREMENT_AUDIT_PERMISSION_REQUIRED','RETIREMENT_SOURCE_SCOPE_DENIED','RETIREMENT_OBJECT_VIEW_DENIED','SOURCE_RECOVERY_OUTCOME_UNCERTAIN','SOURCE_ARCHIVED','SOURCE_ARCHIVE_REVIEW_REQUIRED','SOURCE_CREDENTIAL_CLEANUP_PENDING','AUTH_DENIED','AUTH_REQUIRED','SOURCE_OPERATION_ACTIVE','SOURCE_APPLY_ACTIVE',
  'SOURCE_APPLY_UNCONFIRMED','SOURCE_LIFECYCLE_CONFLICT','SOURCE_RETIREMENT_PENDING',
  'RETIREMENT_UNAVAILABLE','RETIREMENT_CONFLICT','RETIREMENT_BLOCKED','RETIREMENT_UNCERTAIN',
  'RETIREMENT_PERMISSION_DENIED','RETIREMENT_OWNERSHIP_UNPROVEN','RETIREMENT_OWNERSHIP_CONFLICT',
  'RETIREMENT_DEPENDENCIES_CHANGED','RETIREMENT_MANUAL_CHANGE','RETIREMENT_PROTECTED_DEPENDENCY','RETIREMENT_GUARD_CHANGED']);
export async function retirement(source: string, action: 'archive-review'|'retirement-review'|'retire'|'retirement-status'|'retirement-resume',
  payload: {operation_id:string; revision?:string; digest?:string; confirmed?:true; confirmed_source?:string; remove_credentials?:boolean},
  signal: AbortSignal): Promise<Retirement> {
  let response: Response;
  try { response=await fetch(`/api/v1/sources/${encodeURIComponent(source)}/${action}`, {
    method:'POST',signal,credentials:'same-origin',cache:'no-store',
    headers:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},body:JSON.stringify(payload),
  }); } catch { throw new RetirementError('RETIREMENT_UNAVAILABLE'); }
  let value: Retirement;
  try {
    const body=await response.json();
    if (!response.ok) throw new RetirementError(codes.has(body?.error?.code)?body.error.code:'RETIREMENT_UNAVAILABLE');
    value=body;
    if (value.safe_code && !codes.has(value.safe_code)) throw new Error();
    if (value.source_instance!==source || value.operation_id!==payload.operation_id
      || !['READY','SENDING','UNCERTAIN','SUCCEEDED','FINALIZED','BLOCKED'].includes(value.state)
      || !/^[a-f0-9]{64}$/.test(value.digest)
      || (value.purged===true ? value.state!=='FINALIZED'||value.mode!=='FULL_DELETE'||value.revision!=='' : !/^[a-f0-9]{64}$/.test(value.revision))
      || (value.purged!==undefined && typeof value.purged!=='boolean')
      || ![2,4].includes(value.manifest?.format) || (value.manifest.format===2&&(!Number.isSafeInteger(value.manifest.cluster_id) || (value.manifest.cluster_id??0)<=0))
      || (value.manifest.format===4&&(!Array.isArray(value.manifest.retained)||value.manifest.retained.length>10000||value.manifest.retained.some(o=>!['cluster','device','vm','interface','vminterface','disk','ip','mac'].includes(o.kind)||!Number.isSafeInteger(o.id)||o.id<=0||typeof o.present!=='boolean'||typeof o.claimed!=='boolean')))
      || !Array.isArray(value.manifest.objects) || value.manifest.objects.length>10000
      || value.manifest.objects.some(row=>!Array.isArray(row) || row.length!==2
        || !/^(cluster|device|vm|interface|vminterface|disk|ip|mac):[1-9][0-9]*$/.test(row[0]) || !/^[a-f0-9]{64}$/.test(row[1]))
      || new Set(value.manifest.objects.map(row=>row[0])).size!==value.manifest.objects.length) throw new Error();
  } catch (error) {if(error instanceof RetirementError) throw error; throw new RetirementError('RETIREMENT_UNAVAILABLE');}
  return value;
}


export async function retainedContext(source:string,signal:AbortSignal):Promise<import('./lifecycle').SourceLifecycle>{
 const response=await fetch(`/api/v1/sources/${encodeURIComponent(source)}/retirement-context`,{method:'POST',signal,credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},body:'{}'});
 const value=await response.json();
 if(!response.ok||value.source_instance!==source||typeof value.display_name!=='string'||!value.removed_at||!Number.isFinite(Date.parse(value.removed_at))||!/^[a-f0-9]{64}$/.test(value.revision))throw new RetirementError('RETIREMENT_UNAVAILABLE');
 return value;
}
