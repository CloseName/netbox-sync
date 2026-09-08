import {useCallback,useEffect,useRef,useState,type ReactNode,type FormEvent} from 'react';
import {useLocation,useNavigate} from 'react-router-dom';
type State={revision:number;status:string;url:string;completed:boolean;read_token_present:boolean;apply_token_present:boolean;safe_code:string|null;checks:{name:string;type:string;models:string[];ok:boolean}[]};
const states=['FRESH','CONFIGURED','VALIDATING','VALIDATED','READY','ATTENTION'];
const reasons:Record<string,string>={NETWORK_UNREACHABLE:'NetBox is unreachable. Check DNS and network.',TLS_FAILED:'NetBox certificate validation failed.',AUTH_FAILED:'NetBox rejected a token.',PERMISSION_DENIED:'Token permissions do not match the required read/apply roles.',RESPONSE_INVALID:'Unsupported NetBox API response.',PREREQUISITES_MISSING:'Required custom fields are missing or incompatible.',DESTINATION_DENIED:'Destination is outside the approved network policy.',VALIDATION_UNAVAILABLE:'Validation did not complete.',VALIDATION_INTERRUPTED:'Validation was interrupted. Validate again.'};
async function call(action='',body?:unknown):Promise<State>{
 const response=await fetch('/api/v1/bootstrap'+(action?'/'+action:''),{method:body?'POST':'GET',cache:'no-store',headers:body?{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'}:undefined,body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(action==='validate'?55000:12000)});
 if(!response.ok)throw new Error('Request not confirmed');const value=await response.json();
 if(!value||!states.includes(value.status)||!Number.isInteger(value.revision)||typeof value.url!=='string'||typeof value.completed!=='boolean'||typeof value.read_token_present!=='boolean'||typeof value.apply_token_present!=='boolean'||!Array.isArray(value.checks)||value.checks.some((c:any)=>typeof c.name!=='string'||typeof c.type!=='string'||!Array.isArray(c.models)||typeof c.ok!=='boolean'))throw new Error('Unsupported response');return value;
}
export function BootstrapGate({children}:{children:ReactNode}){
 const [state,setState]=useState<State|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const location=useLocation(),navigate=useNavigate();
 const sequence=useRef(0);
 useEffect(()=>{if(state?.status!=='READY'||location.pathname==='/setup')document.title='NetBox setup | NetBox Sync';},[state?.status,location.pathname]);
 const reload=useCallback(async()=>{const id=++sequence.current;try{const next=await call();if(id===sequence.current){setState(next);setError('');}}catch{if(id===sequence.current)setError('Bootstrap state is unavailable. Reload to check readiness.');}},[]);
 useEffect(()=>{void reload();window.addEventListener('focus',reload);return()=>window.removeEventListener('focus',reload);},[reload]);
 useEffect(()=>{if(state?.status!=='VALIDATING')return;const timer=setTimeout(reload,2500);return()=>clearTimeout(timer);},[state,reload]);
 const submit=async(action:string,body:unknown)=>{if(busy)return;setBusy(true);++sequence.current;setError('');try{const next=await call(action,body);++sequence.current;setState(next);if(action==='finish')navigate('/');}catch{setError('Request outcome is unconfirmed. Reload state; no automatic retry.');}finally{setBusy(false);}};
 const configure=(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();const form=event.currentTarget,data=new FormData(form);const body={revision:state!.revision,url:String(data.get('url')),read_token:String(data.get('read_token')),apply_token:String(data.get('apply_token')),replace_credentials:data.get('replace')==='on'};form.reset();void submit('configuration',body);};
 if(state?.status==='READY'&&!error&&location.pathname!=='/setup')return <>{children}</>;
 return <main className="add-source-workspace" style={{maxWidth:900,margin:'2rem auto',padding:'1rem'}}><h1>Welcome to NetBox Sync</h1><p>Connect NetBox before adding sources. Setup runs no discovery or synchronization.</p>
 {error&&<p role="alert">{error}</p>}<button disabled={busy} onClick={reload}>Reload setup state</button>
 {busy&&<p role="status">Waiting for the server to confirm this request...</p>}
 {!state&&<p role="status">Checking first-run state...</p>}
 {state&&<><p role="status">Setup: {state.status.toLowerCase()}</p>{state.safe_code&&<p role="alert">{Object.hasOwn(reasons,state.safe_code)?reasons[state.safe_code]:'Setup requires operator attention.'}</p>}
 <section className="source-panel"><h2>NetBox connection and credentials</h2><p>Use two different tokens. Discovery needs read-only access with token writes disabled. Apply needs view, add and change permissions for managed objects. Do not grant delete permission. Object-specific permissions must allow the intended source scope.</p><p>Tokens cannot be retrieved through this UI. They are cleared from the form after submission. Source credentials are configured later through Sources / Add Source.</p>
 <form className="bootstrap-form" onSubmit={configure} key={state.revision}><label>NetBox HTTPS URL<input name="url" type="url" required defaultValue={state.url} readOnly={state.completed}/></label>{state.completed&&<p>The NetBox URL is fixed after setup. Replace tokens only for this same instance.</p>}
 <label>Read-only token<input name="read_token" type="password" required minLength={8} maxLength={4096} autoComplete="off"/></label><label>Apply token<input name="apply_token" type="password" required minLength={8} maxLength={4096} autoComplete="off"/></label>
 {state.read_token_present&&<label><input name="replace" type="checkbox" required/> Deliberately replace existing stored credentials</label>}<button disabled={busy||state.status==='VALIDATING'}>Save connection</button></form></section>
 {state.status!=='FRESH'&&<section className="source-panel"><h2>Validate connection and prerequisites</h2><p>Checks use GET and OPTIONS only. No infrastructure is created or deleted.</p><button disabled={busy||state.status==='VALIDATING'} onClick={()=>submit('validate',{revision:state.revision})}>Test connection and prerequisites</button>
 {state.checks.length>0&&<><p>Create or correct the listed custom fields in NetBox, then validate again. Existing fields are never overwritten automatically. Site, Cluster, VLAN and Prefix remain operator-owned.</p><ul>{state.checks.map(c=><li key={c.name}>{c.ok?'Valid':'Required'} <code>{c.name}</code>: {c.type}; {c.models.join(', ')}</li>)}</ul></>}</section>}
 {state.status==='VALIDATED'&&<section className="source-panel"><h2>Review and finish</h2><p>NetBox: {state.url}. Separate tokens stored; validation passed. Sources are added separately, with automatic sync off.</p><button className="primary" disabled={busy} onClick={()=>submit('finish',{revision:state.revision})}>Finish setup</button></section>}
 {state.status==='READY'&&<button onClick={()=>navigate('/')}>Open Overview</button>}</>}
 </main>;
}
