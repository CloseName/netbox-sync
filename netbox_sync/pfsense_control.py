"""Root-owned per-VM keys and bounded, unprivileged pfSense network operations."""
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from .bootstrap_state import runtime_netbox
from .local_control import ControlError
from .source_lifecycle import apply_lock
from .discovery_worker import _drop_privileges, _safe_environment
from .child_process import child_process, stop_child

PUBLIC = ('status','error','address','port','verify_tls','username','collected_at','ssh_port')

def public(value):
    return {k:value[k] for k in PUBLIC if k in value}

def atomic(path,value):
    temporary=path.with_suffix('.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)

def handle(store,lock_path,payload):
    from .api.auth import AuthClient
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    if set(payload)!={'action','operation','vm_id','session','data'} or type(payload['vm_id']) is not int or not 0<payload['vm_id']<=2147483647:
        raise ControlError('CONTROL_REQUEST_INVALID')
    operation=payload['operation'];vm=payload['vm_id'];data=payload['data']
    if operation not in ('status','connect','collect'):raise ControlError('CONTROL_REQUEST_INVALID')
    auth=AuthClient('/run/netbox-sync-auth/worker.sock')
    auth.call('authorize',session=payload['session'],permission={'status':'source.read','connect':'source.register','collect':'source.apply'}[operation],audit=operation!='status')
    root=store.root/'pfsense';root.mkdir(mode=0o700,exist_ok=True)
    if root.is_symlink() or root.stat().st_uid!=0 or root.stat().st_mode&0o077:raise ControlError('CONTROL_DIRECTORY_INVALID')
    path=root/(str(vm)+'.json')
    def read():
        if not path.exists():return {'status':'NOT_CONNECTED'}
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            info=os.fstat(stream.fileno())
            if info.st_uid!=0 or info.st_mode&0o077 or info.st_size>16384:raise ControlError('CONTROL_DIRECTORY_INVALID')
            return json.load(stream)
    if operation=='status':
        current=read()
        if current.get('status')=='RUNNING' and time.time()-current.get('started_at',0)>130:
            current.update(status='ATTENTION',error='OUTCOME_UNKNOWN')
        return public(current)
    policy=auth.call('probe.authorize',session=payload['session'],revision=data.get('policy_revision'))['effective']
    with apply_lock(lock_path):
        state=read()
        if operation=='connect':
            from .api.pfsense import Connect
            data=Connect(**data).model_dump();data['password']=payload['data']['password']
            endpoint={k:data[k] for k in ('address','port','verify_tls')}
            if 'key' in state and any(state.get(k)!=endpoint[k] for k in ('address','port')):
                return {'error':'ENDPOINT_CHANGED','status':state['status']}
            if 'key' not in state:
                key=Ed25519PrivateKey.generate()
                state.update(key=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.OpenSSH,serialization.NoEncryption()).decode(),
                    public_key=key.public_key().public_bytes(serialization.Encoding.OpenSSH,serialization.PublicFormat.OpenSSH).decode(),
                    owner=secrets.token_hex(16),username='nb-sync-'+str(vm),**endpoint)
            state.update(endpoint)
        elif 'key' not in state:return {'error':'NOT_CONNECTED'}
        state.update(status='RUNNING',error=None,started_at=time.time())
        atomic(path,state)  # Persist key before any remote mutation; retries reuse it.
        url,read_token=runtime_netbox(store.path,'read')
        _,apply_token=runtime_netbox(store.path,'apply')
        value=dict(vm_id=vm,operation=operation,state=state,data=data,policy=policy,url=url,
            read_token=read_token,apply_token=apply_token,guard_instance=os.environ.get('NETBOX_SYNC_GUARD_INSTANCE',''))
        try:
            with child_process(subprocess.Popen,[sys.executable,'-B','-m','netbox_sync.pfsense_connect'],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                env=_safe_environment(),preexec_fn=_drop_privileges(10001,10001)) as process:
                try: output,_=process.communicate(json.dumps(value).encode(),timeout=115)
                except subprocess.TimeoutExpired:
                    stop_child(process);raise ValueError()
            if process.returncode or len(output)>8192:raise ValueError()
            result=json.loads(output)
        except Exception:result={'error':'OUTCOME_UNKNOWN'}
        if result.get('error'):
            state.update(status='ATTENTION',error=result['error'])
        else:
            state.update(status='CONNECTED',error=None,**{k:result[k] for k in ('collected_at','ssh_port','host_key')})
        atomic(path,state)
        return public(state)
