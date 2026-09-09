"""TEST-ONLY external NetBox stand-in for disposable Docker HTTPS smoke."""
import json
import os
import socket
import time
import ssl
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from netbox_sync.bootstrap_probe import FIELDS

PREPARE = os.environ.get('TEST_PREPARATION') == '1'
ROWS = []
UNCERTAIN = False
REVOKED = False
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def reply(self,value,status=200):
        raw=json.dumps(value).encode();self.send_response(status)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if '/users/tokens/' in self.path:
            row={'id':91,'key':'ABCDEFGHIJKL','version':2}
            self.reply({'count':1,'next':None,'results':[row]} if '?' in self.path else row)
        elif '/custom-fields/' in self.path and PREPARE:self.reply({'next':None,'results':ROWS})
        elif '/custom-fields/' in self.path:
            self.reply(dict(next=None,results=[dict(name=n,type=k,object_types=list(m)) for n,(k,m) in FIELDS.items()]))
        else:self.reply(dict(count=0,results=[]))
    def do_POST(self):
        global UNCERTAIN
        if self.path!='/api/extras/custom-fields/' or self.headers.get('Authorization')!='Bearer nbt_ABCDEFGHIJKL.SETUPSECRET':return self.reply({},403)
        value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if any(row['name']==value['name'] for row in ROWS):return self.reply({},400)
        if value['name']=='sync_identities':time.sleep(1)
        ROWS.append({**value,'id':len(ROWS)+1,'status':{'value':'active'}})
        if value['name']=='cpu_vendor' and not UNCERTAIN:
            UNCERTAIN=True
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        self.reply(ROWS[-1],201)
    def do_DELETE(self):
        global REVOKED
        if self.path!='/api/users/tokens/91/' or self.headers.get('Authorization')!='Bearer nbt_ABCDEFGHIJKL.SETUPSECRET':return self.reply({},403)
        if os.environ.get('TEST_REVOKE_DENIED')=='1':return self.reply({},403)
        REVOKED=True
        self.reply({},204)
    def do_OPTIONS(self):self.reply(dict(actions={} if self.headers.get('Authorization')=='Token TEST-READ-TOKEN' else {'POST':{}}))

if __name__=='__main__':
    server=ThreadingHTTPServer(('0.0.0.0',8443),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain('/tls/fullchain.pem','/tls/privkey.pem')
    server.socket=context.wrap_socket(server.socket,server_side=True)
    server.serve_forever()
