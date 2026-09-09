"""Controlled HTTPS/SOAP peer. Never logs headers, bodies or credentials."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
        if self.headers.get('Host', '').startswith('slow.'):
            time.sleep(7)
        self.respond(b'<namespaces version="1.0"><namespace><version>6.7</version></namespace></namespaces>')
    def do_POST(self):
        body = ET.fromstring(self.rfile.read(min(int(self.headers.get('Content-Length', '0')), 65536)))
        method = next(iter(next(e for e in body if e.tag.endswith('Body'))))
        name = method.tag.split('}')[-1]
        if name == 'RetrieveServiceContent':
            result = '<returnval><rootFolder type="Folder">ha-folder-root</rootFolder><sessionManager type="SessionManager">ha-sessionmgr</sessionManager><about><name>Fixture</name><fullName>Fixture</fullName><vendor>VMware</vendor><version>6.7.0</version><build>1</build><osType>vmnix-x86</osType><productLineId>embeddedEsx</productLineId><apiType>HostAgent</apiType><apiVersion>6.7</apiVersion></about></returnval>'
        elif name == 'Login':
            username = next((e.text for e in method if e.tag.endswith('userName')), '')
            if username == 'reject':
                fault = '<soap:Fault><faultcode>ServerFaultCode</faultcode><faultstring>REMOTE_DETAIL_MUST_NOT_ESCAPE</faultstring><detail><InvalidLoginFault xmlns="urn:vim25" xsi:type="InvalidLogin"/></detail></soap:Fault>'
                return self.soap(fault, 500)
            result = '<returnval><key>fixture</key><userName>fixture</userName><fullName>fixture</fullName><loginTime>2026-01-01T00:00:00Z</loginTime><lastActiveTime>2026-01-01T00:00:00Z</lastActiveTime><locale>en</locale><messageLocale>en</messageLocale></returnval>'
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
