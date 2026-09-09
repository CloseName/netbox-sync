"""Controlled HTTPS/SOAP peer. Never logs headers, bodies or credentials."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import urlsplit,parse_qs
import ssl
import time
from xml.etree import ElementTree as ET

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def respond(self, body, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'text/xml')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try: self.wfile.write(body)
        except (OSError, ssl.SSLError): pass
    def do_GET(self):
        if self.path.startswith('/api/'):
            path=urlsplit(self.path).path.strip('/').split('/')
            kind=path[2]
            rows={'sites':dict(id=1,name='Test site',slug='dc1'),
                'clusters':dict(id=2,name='Test',type={'id':3,'name':'VMware ESXi'},scope_type='dcim.site',scope_id=1,scope={'id':1,'name':'Test site'}),
                'cluster-types':dict(id=3,name='VMware ESXi',slug='vmware-esxi'),
                'platforms':dict(id=4,name='VMware ESXi',slug='vmware-esxi'),
                'device-roles':dict(id=5,name='Hypervisor',slug='server'),
                'device-types':dict(id=6,model='PowerEdge R650',slug='r650',manufacturer={'id':7,'name':'Dell Inc.'})}
            if kind not in rows:return self.respond(b'{}',404)
            row=rows[kind]
            if len(path)>3:
                return self.respond(json.dumps(row).encode(),200 if path[3]==str(row['id']) else 404)
            return self.respond(json.dumps(dict(results=[row],count=1,next=None,previous=None)).encode())
        if self.headers.get('Host', '').startswith('slow.'):
            time.sleep(7)
        self.respond(b'<namespaces version="1.0"><namespace><version>6.7</version></namespace></namespaces>')
    def do_POST(self):
        body = ET.fromstring(self.rfile.read(min(int(self.headers.get('Content-Length', '0')), 65536)))
        method = next(iter(next(e for e in body if e.tag.endswith('Body'))))
        name = method.tag.split('}')[-1]
        if name == 'RetrieveServiceContent':
            result = '<returnval><rootFolder type="Folder">ha-folder-root</rootFolder><propertyCollector type="PropertyCollector">ha-property-collector</propertyCollector><sessionManager type="SessionManager">ha-sessionmgr</sessionManager><about><name>Fixture</name><fullName>Fixture</fullName><vendor>VMware</vendor><version>6.7.0</version><build>1</build><osType>vmnix-x86</osType><productLineId>embeddedEsx</productLineId><apiType>HostAgent</apiType><apiVersion>6.7</apiVersion></about></returnval>'
        elif name == 'Login':
            username = next((e.text for e in method if e.tag.endswith('userName')), '')
            if username == 'reject':
                fault = '<soap:Fault><faultcode>ServerFaultCode</faultcode><faultstring>REMOTE_DETAIL_MUST_NOT_ESCAPE</faultstring><detail><InvalidLoginFault xmlns="urn:vim25" xsi:type="InvalidLogin"/></detail></soap:Fault>'
                return self.soap(fault, 500)
            result = '<returnval><key>fixture</key><userName>fixture</userName><fullName>fixture</fullName><loginTime>2026-01-01T00:00:00Z</loginTime><lastActiveTime>2026-01-01T00:00:00Z</lastActiveTime><locale>en</locale><messageLocale>en</messageLocale></returnval>'
        elif name in ('RetrieveProperties','RetrievePropertiesEx','Fetch'):
            object_element=next(e for e in method.iter() if e.tag.endswith('_this' if name=='Fetch' else 'obj'))
            object_id=object_element.text
            path=next(e.text for e in method.iter() if e.tag.endswith('prop' if name=='Fetch' else 'pathSet'))
            if object_id=='ha-folder-root' and path=='childEntity':
                val='<val xsi:type="ArrayOfManagedObjectReference"><ManagedObjectReference type="HostSystem">ha-host</ManagedObjectReference></val>'
            elif object_id=='ha-host' and path=='name':val='<val xsi:type="xsd:string" xmlns:xsd="http://www.w3.org/2001/XMLSchema">esxi.probe.test</val>'
            elif object_id=='ha-host' and path=='summary':
                val='<val xsi:type="HostListSummary"><hardware><vendor>Dell Inc.</vendor><model>PowerEdge R650</model><uuid>12345678-1234-4321-8765-123456789abc</uuid><memorySize>34359738368</memorySize><cpuModel>Fixture CPU</cpuModel><cpuMhz>2400</cpuMhz><numCpuPkgs>1</numCpuPkgs><numCpuCores>8</numCpuCores><numCpuThreads>16</numCpuThreads><numNics>2</numNics><numHBAs>1</numHBAs></hardware><config><name>esxi.probe.test</name><product><name>VMware ESXi</name><fullName>VMware ESXi</fullName><vendor>VMware</vendor><version>6.7.0</version><build>1</build><osType>vmnix-x86</osType><productLineId>embeddedEsx</productLineId><apiType>HostAgent</apiType><apiVersion>6.7</apiVersion></product></config></val>'
            else:return self.respond(b'',400)
            record='<obj type="'+object_element.attrib.get('type','HostSystem')+'">'+object_id+'</obj><propSet><name>'+path+'</name>'+val+'</propSet>'
            result=(val.replace('<val','<returnval').replace('</val>','</returnval>') if name=='Fetch' else '<returnval>'+('<objects>'+record+'</objects>' if name.endswith('Ex') else record)+'</returnval>')
            if name=='Fetch' and path=='childEntity': result='<returnval type="HostSystem">ha-host</returnval>'
        elif name == 'Logout': result = ''
        else: return self.respond(b'', 400)
        self.soap('<' + name + 'Response xmlns="urn:vim25">' + result + '</' + name + 'Response>')
    def soap(self, body, status=200):
        self.respond(('<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><soap:Body>' + body + '</soap:Body></soap:Envelope>').encode(), status)

server = ThreadingHTTPServer(('0.0.0.0', 443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain('/fixture/server.crt', '/fixture/server.key')
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
