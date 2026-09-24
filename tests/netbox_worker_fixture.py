"""Real NetBox TLS Unix endpoint for the isolated production worker test."""
import json
import os
from pathlib import Path
import socket
import socketserver
import threading
import time
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler


def exercise(context,application,certfile,source,cluster,instance,token,direct_url,catalog_slug,vrfs):
    assert Path('/.dockerenv').is_file() and os.environ.get('NETBOX_SYNC_GUARD_WORKER_TEST')=='1'
    root=Path('/fixture')
    for name,mode in (('bridge',0o755),('worker',0o755),('config',0o700),('ca',0o755)):
        (root/name).mkdir(mode=mode)
    ca=root/'ca/netbox-ca.pem';ca.write_bytes(certfile.read_bytes());ca.chmod(0o644)
    config=root/'config/bootstrap.json';config.touch(mode=0o600)
    config.write_text(json.dumps({'format':1,'status':'READY','url':'https://guard-netbox.test:8443',
                                  'apply_token':token}),encoding='utf-8')
    class UnixServer(WSGIServer):
        address_family=socket.AF_UNIX
        def server_bind(self):
            socketserver.TCPServer.server_bind(self)
            self.server_name='guard-netbox.test';self.server_port=8443;self.setup_environ()
        def get_request(self):
            request,_=super().get_request();return request,('127.0.0.1',0)
    class Quiet(WSGIRequestHandler):
        def log_message(self,*args):pass
    server=UnixServer(str(root/'bridge/netbox.sock'),Quiet)
    server.set_app(application)
    # Only the test byte relay mounts this fixture directory. Public TLS remains
    # end-to-end between real worker and NetBox WSGI; relay cannot read payloads.
    (root/'bridge/netbox.sock').chmod(0o666)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    (root/'bridge/ready.json').write_text(json.dumps({'guard_instance':instance,'source':source,'cluster':cluster,'direct_url':direct_url,'catalog_slug':catalog_slug,'vrfs':vrfs}))
    try:
        deadline=time.monotonic()+240
        while not (root/'bridge/done.json').exists():
            if time.monotonic()>deadline:raise AssertionError('isolated worker gate did not finish')
            time.sleep(.1)
        assert json.loads((root/'bridge/done.json').read_text())=={'passed':True}
    finally:
        server.shutdown();server.server_close();thread.join(3)
