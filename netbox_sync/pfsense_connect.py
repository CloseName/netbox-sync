"""Single-use child: authenticated pfSense GUI setup, pinned SSH, guarded import."""
import base64
import io
import json
import re
import socket
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import requests
from .api.egress import EgressPolicy, pinned_dns
from .bootstrap_probe import fetch, ProbeError
from .netbox_tls import configure_session
from .source_tls import CA_FILE
from .netbox_auth import authorization
from .pfsense_preview import build_preview

ASSETS = Path('/app/deploy/pfsense')

class SetupError(Exception): pass

class Page(HTMLParser):
    def __init__(self,text):
        super().__init__();self.token=None;self.pre=False;self.output=[];self.feed(text)
        if not self.token:
            match=re.search(r'csrfMagicToken\s*=\s*[\'"]([^\'"]+)',text)
            if match:self.token=match[1]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='input' and attrs.get('name')=='__csrf_magic':self.token=attrs.get('value')
        if tag=='pre':self.pre=True
    def handle_endtag(self,tag):
        if tag=='pre':self.pre=False
    def handle_data(self,data):
        if self.pre:self.output.append(data)
    def result(self):
        matches=re.findall(r'NS_RESULT:([A-Za-z0-9+/=]+)', ''.join(self.output))
        if len(matches)!=1:raise SetupError('GUI_COMMAND_FAILED')
        return json.loads(base64.b64decode(matches[0],validate=True))

def gui_request(session,url,data=None):
    with session.request('POST' if data else 'GET',url,data=data,timeout=(5,15),allow_redirects=False,stream=True) as response:
        if response.status_code not in (200,302):raise SetupError('GUI_ACCESS_DENIED')
        # A successful login redirects; never forward credentials to that location.
        if response.status_code==302:return ''
        raw=bytearray()
        for chunk in response.iter_content(16384):
            raw.extend(chunk)
            if len(raw)>2*1024*1024:raise SetupError('GUI_RESPONSE_TOO_LARGE')
        return raw.decode('utf-8',errors='replace')

def php(session,base,code):
    page=Page(gui_request(session,base+'/diag_command.php'))
    if not page.token:raise SetupError('GUI_ACCESS_DENIED')
    return Page(gui_request(session,base+'/diag_command.php',{'__csrf_magic':page.token,
        'submit':'EXECPHP','txtPHPCommand':code})).result()

PROBE = """echo 'NS_RESULT:' . base64_encode(json_encode([
'version'=>trim(file_get_contents('/etc/version')),
'ssh_port'=>(int)(config_get_path('system/ssh/port', 22) ?: 22),
'ssh_enabled'=>array_key_exists('enable', config_get_path('system/ssh', [])),
'host_key'=>trim(file_get_contents('/etc/ssh/ssh_host_ed25519_key.pub')),
'ifconfig'=>shell_exec('/sbin/ifconfig -a')]));"""

def setup(value, interfaces):
    state=value['state'];data=value['data'];port=state['port']
    host,address=EgressPolicy(**value['policy']).resolve(state['address'],port)
    with pinned_dns(host,address,port),requests.Session() as session:
        configure_session(session,CA_FILE)
        if not state['verify_tls']:session.verify=False
        base='https://'+host+(':'+str(port) if port!=443 else '')
        session.headers['Referer']=base+'/'
        page=Page(gui_request(session,base+'/'))
        if not page.token:raise SetupError('GUI_LOGIN_UNSUPPORTED')
        gui_request(session,base+'/',{'__csrf_magic':page.token,'usernamefld':data['username'],
            'passwordfld':data['password'],'login':'Sign In'})
        probe=php(session,base,PROBE)
        if probe.get('version')!='2.7.2-RELEASE':raise SetupError('UNSUPPORTED_VERSION')
        if not probe.get('ssh_enabled'):raise SetupError('SSH_DISABLED')
        expected={r['mac'].lower() for r in interfaces if r['mac']}
        actual=set(re.findall(r'ether ([0-9a-f:]{17})',probe['ifconfig'].lower()))
        if not expected or len(expected)!=len(interfaces) or not expected.issubset(actual):raise SetupError('VM_IDENTITY_MISMATCH')
        if state.get('host_key') and state['host_key']!=probe['host_key']:raise SetupError('SSH_HOST_KEY_CHANGED')
        if not 1<=probe['ssh_port']<=65535 or not probe['host_key'].startswith('ssh-ed25519 '):raise SetupError('SSH_CONFIGURATION_INVALID')
        files={name:base64.b64encode((ASSETS/name).read_bytes()).decode()
               for name in ('network-v1.php','inventory-v1.php','pf-runtime-v1.php')}
        payload=dict(username=state['username'],owner=state['owner'],public_key=state['public_key'],files=files)
        code='$ns_input=json_decode(base64_decode("'+base64.b64encode(json.dumps(payload).encode()).decode()+'"), true);\n'
        code+=(ASSETS/'provision-web.php').read_text(encoding='utf-8')
        result=php(session,base,code)
        if result.get('error') in {'USER_CONFLICT','PATH_CONFLICT','INSTALL_FAILED','INVALID_USER','INVALID_UID','SSH_DISABLED','UNSUPPORTED_VERSION'}:raise SetupError(result['error'])
        if result.get('installed') is not True:raise SetupError('INSTALL_FAILED')
        return probe

def collect(state,policy):
    import paramiko
    host,address=EgressPolicy(**policy).resolve(state['address'],state['ssh_port'])
    key=paramiko.Ed25519Key.from_private_key(io.StringIO(state['key']))
    parts=state['host_key'].split()
    public=paramiko.Ed25519Key(data=base64.b64decode(parts[1],validate=True))
    client=paramiko.SSHClient()
    client.get_host_keys().add(host if state['ssh_port']==22 else '['+host+']:'+str(state['ssh_port']),'ssh-ed25519',public)
    with socket.create_connection((address,state['ssh_port']),timeout=5) as sock:
        try:
            client.connect(host,port=state['ssh_port'],sock=sock,username=state['username'],pkey=key,
                allow_agent=False,look_for_keys=False,timeout=5,auth_timeout=8,banner_timeout=8)
            channel=client.get_transport().open_session(timeout=8);channel.settimeout(8)
            channel.exec_command('netbox-sync-inventory-v1');channel.shutdown_write()
            raw=bytearray();deadline=time.monotonic()+30
            while True:
                if time.monotonic()>deadline:raise SetupError('COLLECT_TIMEOUT')
                if channel.recv_ready():
                    raw.extend(channel.recv(65536))
                    if len(raw)>8*1024*1024:raise SetupError('SNAPSHOT_TOO_LARGE')
                elif channel.exit_status_ready():break
                else:time.sleep(.02)
                if channel.recv_stderr_ready():
                    if channel.recv_stderr(8192):raise SetupError('COLLECT_FAILED')
            if channel.recv_exit_status()!=0:raise SetupError('COLLECT_FAILED')
            return json.loads(raw)
        finally:client.close()

def run(value, progress=None):
    parsed=urlsplit(value['url']);host,address=EgressPolicy(allowed_hosts=(parsed.hostname,)).resolve(parsed.hostname,parsed.port or 443)
    with pinned_dns(host,address,parsed.port or 443),requests.Session() as session:
        configure_session(session)
        vm=fetch(session,value['url']+'/api/virtualization/virtual-machines/'+str(value['vm_id'])+'/',value['read_token'])
        if 'pfsense' not in vm['name'].casefold():raise SetupError('VM_NOT_PFSENSE')
        page=fetch(session,value['url']+'/api/virtualization/interfaces/?virtual_machine_id='+str(value['vm_id'])+'&limit=512',value['read_token'])
        if page.get('next') or page['count']!=len(page['results']):raise SetupError('VM_INTERFACES_INVALID')
        interfaces=[dict(id=r['id'],vm_id=value['vm_id'],name=r['name'],mac=(r.get('primary_mac_address') or {}).get('mac_address')) for r in page['results']]
        response=session.post(value['url']+'/api/plugins/netbox-sync-guard/pfsense/preflight/',
            json={'vm_id':value['vm_id']},headers={'Authorization':authorization(value['apply_token']),
            'X-Netbox-Sync-Guard-Instance':value['guard_instance']},timeout=(5,15),allow_redirects=False)
        if response.status_code==404:raise SetupError('GUARD_UPGRADE_REQUIRED')
        if response.status_code!=200:
            try:code=response.json().get('code')
            except (ValueError,AttributeError):code=None
            allowed={'PERMISSION_DENIED','TOKEN_WRITE_REQUIRED','GUARD_INSTANCE_CHANGED','PFSENSE_FIELDS_REQUIRED','PFSENSE_FIELDS_INCOMPATIBLE'}
            raise SetupError(code if code in allowed else 'NETBOX_PREFLIGHT_FAILED')
        if response.json().get('status')!='READY':raise SetupError('NETBOX_PREFLIGHT_FAILED')
    state=dict(value['state'])
    if value['operation']=='connect':state.update({k:v for k,v in setup(value,interfaces).items() if k in ('ssh_port','host_key')})
    if 'host_key' not in state:raise SetupError('CONNECT_REQUIRED')
    if progress is not None:progress.update(ssh_port=state['ssh_port'],host_key=state['host_key'])
    snapshot=collect(state,value['policy'])
    snapshot['collection_interval_seconds']=(value.get('data',{}).get('interval_minutes',state.get('interval_minutes',60)) if value['operation']=='connect' else state.get('interval_minutes',60))*60
    preview=build_preview(snapshot['network'],interfaces,value['vm_id'])
    if not preview['all_interfaces_matched'] or preview['unmatched_vm_interfaces']:raise SetupError('VM_IDENTITY_MISMATCH')
    with pinned_dns(host,address,parsed.port or 443),requests.Session() as session:
        configure_session(session)
        response=session.post(value['url']+'/api/plugins/netbox-sync-guard/pfsense/import/',
            json={'vm_id':value['vm_id'],'snapshot':snapshot},
            headers={'Authorization':authorization(value['apply_token']),'X-Netbox-Sync-Guard-Instance':value['guard_instance']},
            timeout=(5,15),allow_redirects=False)
        if response.status_code!=200:
            try:code=response.json().get('code')
            except (ValueError,AttributeError):code=None
            allowed={'PERMISSION_DENIED','TOKEN_WRITE_REQUIRED','GUARD_INSTANCE_CHANGED','PFSENSE_FIELDS_REQUIRED','PFSENSE_FIELDS_INCOMPATIBLE','PFSENSE_SNAPSHOT_INVALID'}
            raise SetupError(code if code in allowed else 'NETBOX_IMPORT_FAILED')
        result=response.json()
        if result.get('status') not in ('SAVED','UNCHANGED'):raise SetupError('NETBOX_IMPORT_FAILED')
    return dict(collected_at=snapshot['collected_at'],ssh_port=state['ssh_port'],host_key=state['host_key'])

def main():
    progress={}
    try:result=run(json.loads(sys.stdin.buffer.read(32769)),progress)
    except SetupError as error:result={'error':str(error)}
    except requests.exceptions.SSLError:result={'error':'TLS_FAILED'}
    except Exception:result={'error':'CONNECTION_FAILED'}
    print(json.dumps({**progress,**result}))

if __name__=='__main__':main()
