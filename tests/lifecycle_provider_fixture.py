"""Synthetic AM SOAP + PVE endpoint, isolated local tests only."""
import ssl
from http.server import ThreadingHTTPServer
from uuid import UUID
from tests.full_sync_https_fixture import Handler as ProviderHandler,properties
from tests.fakes.am_conflicts import CASES
from html import escape

base={key:value for (obj,key),value in properties.items() if obj=='vm-42'}
properties[('ha-host','vm')]='<val xsi:type="ArrayOfManagedObjectReference">'+''.join(
    '<ManagedObjectReference type="VirtualMachine">vm-'+str(i)+'</ManagedObjectReference>' for i in range(1,len(CASES)+1))+'</val>'
for i,(name,addresses) in enumerate(CASES,1):
    mac='00:50:56:00:00:'+format(i,'02x');obj='vm-'+str(i)
    for key,value in base.items():
        properties[(obj,key)]=value.replace('ESXI-VM',escape(name)).replace('42000000-1111-2222-3333-0123456789ab',str(UUID(int=i))).replace('503c5ad7-0000-1111-2222-0123456789ab',str(UUID(int=100+i))).replace('00:50:56:aa:bb:01',mac)
    properties[(obj,'guest')]='<val xsi:type="GuestInfo"><net><network>VM Network</network><macAddress>'+mac+'</macAddress><connected>true</connected><deviceConfigId>4000</deviceConfigId><ipConfig>'+''.join('<ipAddress><ipAddress>'+a.split('/')[0]+'</ipAddress><prefixLength>'+a.split('/')[1]+'</prefixLength></ipAddress>' for a in addresses)+'</ipConfig></net></val>'
class Handler(ProviderHandler):
    hold_inventory=False
    def do_POST(self):
        if self.path=='/fixture/hold-next-inventory':
            Handler.hold_inventory=True
            return self.respond(b'{}')
        if Handler.hold_inventory and self.path.startswith('/sdk'):
            import io,time
            data=self.rfile.read(min(int(self.headers.get('Content-Length','0')),65536))
            self.rfile=io.BytesIO(data)
            if b'RetrieveProperties' in data:
                Handler.hold_inventory=False;time.sleep(3)
        return super().do_POST()
server=ThreadingHTTPServer(('0.0.0.0',8443),Handler)
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain('/fixture/server.crt','/fixture/server.key')
server.socket=context.wrap_socket(server.socket,server_side=True);server.serve_forever()
