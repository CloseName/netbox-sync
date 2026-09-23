export type RetirementState = 'READY' | 'SENDING' | 'UNCERTAIN' | 'SUCCEEDED' | 'FINALIZED' | 'BLOCKED';
export interface Retirement {
  source_instance: string; operation_id: string; state: RetirementState; digest: string;
  revision: string; guard_instance: string; remove_credentials?: boolean | null;
  manifest: {format: 2; cluster_id: number; objects: [string,string][]; retained_cluster?: boolean};
}
export class RetirementError extends Error {
  constructor(readonly code: string) {super(code);}
}
const codes = new Set(['AUTH_DENIED','AUTH_REQUIRED','SOURCE_OPERATION_ACTIVE','SOURCE_APPLY_ACTIVE',
  'SOURCE_APPLY_UNCONFIRMED','SOURCE_LIFECYCLE_CONFLICT','SOURCE_RETIREMENT_PENDING',
  'RETIREMENT_UNAVAILABLE','RETIREMENT_CONFLICT','RETIREMENT_BLOCKED','RETIREMENT_UNCERTAIN']);
export async function retirement(source: string, action: 'retirement-review'|'retire'|'retirement-status'|'retirement-resume',
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
    if (value.source_instance!==source || value.operation_id!==payload.operation_id
      || !['READY','SENDING','UNCERTAIN','SUCCEEDED','FINALIZED','BLOCKED'].includes(value.state)
      || !/^[a-f0-9]{64}$/.test(value.digest) || !/^[a-f0-9]{64}$/.test(value.revision)
      || value.manifest?.format!==2 || !Number.isSafeInteger(value.manifest.cluster_id) || value.manifest.cluster_id<=0
      || !Array.isArray(value.manifest.objects) || value.manifest.objects.length>10000
      || value.manifest.objects.some(row=>!Array.isArray(row) || row.length!==2
        || !/^(cluster|device|vm|interface|vminterface|disk|ip|mac):[1-9][0-9]*$/.test(row[0]) || !/^[a-f0-9]{64}$/.test(row[1]))
      || new Set(value.manifest.objects.map(row=>row[0])).size!==value.manifest.objects.length) throw new Error();
  } catch (error) {if(error instanceof RetirementError) throw error; throw new RetirementError('RETIREMENT_UNAVAILABLE');}
  return value;
}
