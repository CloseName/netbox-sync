"""Controlled provider HTTPS/SOAP and NetBox REST; real SDKs remain in workers."""
import json, ssl, threading
from http.server import ThreadingHTTPServer
from xml.etree import ElementTree as ET
from tests.probe_https_fixture import Handler as ProbeHandler
from tests.sample_data import proxmox_responses
from tests.fakes import FakeNetBox, FakeRecord
from tests.netbox_scenarios import add_target
from tests.fakes.netbox_http import netbox_http

class Handler(ProbeHandler):
    def do_GET(self):
        if self.path.startswith('/api2/json/'):
            key=tuple(int(p) if p.isdigit() else p for p in self.path.split('?')[0][11:].split('/'))
            data={'version':'8.3.2'} if key==('version',) else proxmox_responses().get(key)
            return self.respond(json.dumps({'data':data}).encode(),200 if data is not None else 404)
        if self.path=='/fixture/state':
            return self.respond(json.dumps({key:len(value) for key,value in rows.items()}).encode())
        return super().do_GET()
    def do_POST(self):
        body=self.rfile.read(min(int(self.headers.get('Content-Length','0')),65536))
        root=ET.fromstring(body)
        method=next(iter(next(e for e in root if e.tag.endswith('Body'))))
        name=method.tag.split('}')[-1]
        if name in ('Fetch','RetrieveProperties','RetrievePropertiesEx'):
            obj=next(e for e in method.iter() if e.tag.endswith('_this' if name=='Fetch' else 'obj'))
            path=next(e.text for e in method.iter() if e.tag.endswith('prop' if name=='Fetch' else 'pathSet'))
            value=properties.get((obj.text,path))
            if value is not None:
                record='<obj type="'+obj.attrib.get('type','HostSystem')+'">'+obj.text+'</obj><propSet><name>'+path+'</name>'+value+'</propSet>'
                result=value.replace('<val','<returnval').replace('</val>','</returnval>') if name=='Fetch' else '<returnval>'+('<objects>'+record+'</objects>' if name.endswith('Ex') else record)+'</returnval>'
                return self.soap('<'+name+'Response xmlns="urn:vim25">'+result+'</'+name+'Response>')
        import io
        self.rfile=io.BytesIO(body)
        return super().do_POST()

properties={
 ('ha-host','vm'):'<val xsi:type="ArrayOfManagedObjectReference"><ManagedObjectReference type="VirtualMachine">vm-42</ManagedObjectReference></val>',
 ('ha-host','hardware'):'<val xsi:type="HostHardwareInfo"><systemInfo><vendor>Dell Inc.</vendor><model>PowerEdge R650</model><uuid>12345678-1234-4321-8765-123456789abc</uuid></systemInfo><cpuInfo><numCpuPackages>1</numCpuPackages><numCpuCores>8</numCpuCores><numCpuThreads>16</numCpuThreads><hz>2400000000</hz></cpuInfo><memorySize>34359738368</memorySize></val>',
 ('ha-host','config'):'<val xsi:type="HostConfigInfo"/>',
 ('ha-host','datastore'):'<val xsi:type="ArrayOfManagedObjectReference"/>',
 ('vm-42','name'):'<val xsi:type="xsd:string" xmlns:xsd="http://www.w3.org/2001/XMLSchema">ESXI-VM</val>',
 ('vm-42','config'):'<val xsi:type="VirtualMachineConfigInfo"><name>ESXI-VM</name><uuid>42000000-1111-2222-3333-0123456789ab</uuid><instanceUuid>503c5ad7-0000-1111-2222-0123456789ab</instanceUuid><hardware><numCPU>4</numCPU><memoryMB>8192</memoryMB></hardware></val>',
 ('vm-42','runtime'):'<val xsi:type="VirtualMachineRuntimeInfo"><powerState>poweredOn</powerState></val>',
 ('vm-42','guest'):'<val xsi:type="GuestInfo"/>',
}
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain('/fixture/server.crt','/fixture/server.key')
seed=FakeNetBox();add_target(seed)
seed.dcim.device_roles.add(FakeRecord(id=4,name='Server',slug='server'))
seed.dcim.platforms.add(FakeRecord(id=5,name='Proxmox',slug='proxmox'))
seed.dcim.device_types.add(FakeRecord(id=6,model='PowerEdge R650',slug='r650',manufacturer=FakeRecord(id=7,name='Dell Inc.')))
seed.dcim.device_types.add(FakeRecord(id=8,model='Reviewed replacement',slug='replacement',manufacturer=FakeRecord(id=7,name='Dell Inc.')))
with netbox_http(seed,context,bind=('0.0.0.0',9443),public_base='https://netbox.example.test:9443') as (_api,rows,writes):
    server=ThreadingHTTPServer(('0.0.0.0',8443),Handler)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    server.serve_forever()
