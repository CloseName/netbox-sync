"""Controlled provider HTTPS/SOAP and NetBox REST; real SDKs remain in workers."""
import json, ssl, threading
from http.server import ThreadingHTTPServer
from xml.etree import ElementTree as ET
from tests.probe_https_fixture import Handler as ProbeHandler
from tests.sample_data import proxmox_responses
from tests.fakes import FakeNetBox, FakeRecord
from tests.netbox_scenarios import add_target
from tests.fakes.netbox_http import netbox_http

provider_rows=proxmox_responses()
secondary=proxmox_responses('node-b')
secondary[('nodes','node-b','qemu')]=[];secondary[('nodes','node-b','lxc')]=[]
secondary[('nodes','node-b','network')][0]['cidr']='10.20.30.11/24'
provider_rows.update({key:value for key,value in secondary.items() if key[:2]==('nodes','node-b')})
provider_rows[('nodes',)].append({'node':'node-b','status':'online'})
provider_rows[('cluster','status')].append({'type':'node','name':'node-b','ip':'10.20.30.11'})
node_reads=0
class Handler(ProbeHandler):
    def soap(self, body, status=200):
        # The full-sync inventory is a different physical host from auth-test.
        # Apply the same identity to both preview summary and batch hardware data.
        body = body.replace('12345678-1234-4321-8765-123456789abc',
                            '22345678-1234-4321-8765-123456789abc')
        return super().soap(body, status)

    def do_GET(self):
        if self.path.startswith('/api2/json/'):
            key=tuple(int(p) if p.isdigit() else p for p in self.path.split('?')[0][11:].split('/'))
            data={'version':'8.3.2'} if key==('version',) else provider_rows.get(key)
            if key==('nodes',):
                global node_reads
                node_reads+=1
                data=list(reversed(data)) if node_reads%2 else list(data)
            return self.respond(json.dumps({'data':data}).encode(),200 if data is not None else 404)
        if self.path=='/fixture/state':
            return self.respond(json.dumps({**{key:len(value) for key,value in rows.items()}, 'write_requests':len(writes), 'observation_interfaces':sum(bool(r.get('custom_fields',{}).get('sync_network_observations')) for r in rows['virtualization.interfaces'].values()), 'legacy_disk_reads':sum('/virtual-disks/' in path for _,path in requests), 'invalid_virtual_requests':sum('/-' in path or '=-' in path for _,path in requests)}).encode())
        return super().do_GET()
    def do_POST(self):
        if self.path=='/fixture/observe-esxi':
            key=('vm-42','guest')
            marker='<ipAddress><ipAddress>10.20.40.42</ipAddress><prefixLength>24</prefixLength></ipAddress>'
            properties[key]=properties[key].replace(marker,marker+'<ipAddress><ipAddress>10.20.40.42</ipAddress><prefixLength>32</prefixLength></ipAddress>')
            return self.respond(b'{}')
        if self.path=='/fixture/observe-proxmox':
            for key,value in provider_rows.items():
                if key[-1:] == ('network-get-interfaces',):
                    for nic in value['result']:
                        for address in list(nic.get('ip-addresses',[])):
                            if address.get('ip-address')=='10.20.30.40':
                                nic['ip-addresses'].append({**address,'prefix':32})
            return self.respond(b'{}')
        if self.path=='/fixture/fail-next-write':
            behavior['fail_write_number']=len(writes)+1
            return self.respond(b'{}')
        if self.path=='/fixture/partial-apply':
            behavior['fail_write_number']=len(writes)+3
            return self.respond(b'{}')
        if self.path=='/fixture/deny-required':
            behavior['deny_reads']=['dcim.devices','virtualization.virtual_disks']
            return self.respond(b'{}')
        if self.path=='/fixture/allow-required':
            behavior['deny_reads']=['virtualization.virtual_disks']
            return self.respond(b'{}')
        if self.path=='/fixture/change-esxi-memory':
            properties[('vm-42','config')]=properties[('vm-42','config')].replace('<memoryMB>8192</memoryMB>','<memoryMB>16384</memoryMB>')
            return self.respond(b'{}')
        if self.path=='/fixture/change-memory':
            provider_rows[('nodes','node-a','status')]['memory']['total']+=1024**3
            return self.respond(b'{}')
        body=self.rfile.read(min(int(self.headers.get('Content-Length','0')),65536))
        root=ET.fromstring(body)
        method=next(iter(next(e for e in root if e.tag.endswith('Body'))))
        name=method.tag.split('}')[-1]
        from tests.fakes.esxi_property_reply import property_reply
        reply = property_reply(method, properties)
        if reply is not None: return self.soap(reply)
        import io
        self.rfile=io.BytesIO(body)
        return super().do_POST()

from tests.fakes.esxi_properties import properties

context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain('/fixture/server.crt','/fixture/server.key')
seed=FakeNetBox();add_target(seed)
from netbox_sync.prerequisites import definition
seed.extras.custom_fields.add(FakeRecord(id=77,**definition('sync_network_observations')))
seed.virtualization.clusters.add(FakeRecord(id=9,name='Proxmox Fixture Cluster',type=seed.virtualization.cluster_types.get(id=2),scope_type='dcim.site',scope_id=1))
seed.dcim.device_roles.add(FakeRecord(id=4,name='Server',slug='server'))
seed.dcim.platforms.add(FakeRecord(id=5,name='Proxmox',slug='proxmox'))
seed.dcim.device_types.add(FakeRecord(id=6,model='PowerEdge R650',slug='r650',manufacturer=FakeRecord(id=7,name='Dell Inc.')))
seed.dcim.device_types.add(FakeRecord(id=8,model='Reviewed replacement',slug='replacement',manufacturer=FakeRecord(id=7,name='Dell Inc.')))
requests=[]
behavior={'reverse_reads':True,'deny_reads':['virtualization.virtual_disks']}
with netbox_http(seed,context,requests=requests,behavior=behavior,bind=('0.0.0.0',9443),public_base='https://netbox.example.test:9443') as (_api,rows,writes):
    server=ThreadingHTTPServer(('0.0.0.0',8443),Handler)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    server.serve_forever()
