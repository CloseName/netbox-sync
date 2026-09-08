"""TEST-ONLY external NetBox stand-in for disposable Docker HTTPS smoke."""
import json
import ssl
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from netbox_sync.bootstrap_probe import FIELDS

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def reply(self,value):
        raw=json.dumps(value).encode();self.send_response(200)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if '/custom-fields/' in self.path:
            self.reply(dict(next=None,results=[dict(name=n,type=k,object_types=list(m)) for n,(k,m) in FIELDS.items()]))
        else:self.reply(dict(count=0,results=[]))
    def do_OPTIONS(self):self.reply(dict(actions={} if self.headers.get('Authorization')=='Token TEST-READ-TOKEN' else {'POST':{}}))

if __name__=='__main__':
    server=ThreadingHTTPServer(('0.0.0.0',8443),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain('/tls/fullchain.pem','/tls/privkey.pem')
    server.socket=context.wrap_socket(server.socket,server_side=True)
    server.serve_forever()
