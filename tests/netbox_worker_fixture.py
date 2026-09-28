"""Real NetBox TLS Unix endpoint for the isolated production worker test."""
import json
import os
from pathlib import Path
import socket
import socketserver
import threading
import time
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler


def exercise(context,application,certfile,source,cluster,instance,token,direct_url,catalog_slug,vrfs,permission_id=None):
    assert Path('/.dockerenv').is_file() and os.environ.get('NETBOX_SYNC_GUARD_WORKER_TEST')=='1'
    import faulthandler
    faulthandler.dump_traceback_later(1900 if os.environ.get('NETBOX_SYNC_FULL_LIFECYCLE')=='1' else 300, exit=True)
    import runpy
    runpy.run_path('/app/tests/netbox_missing_cluster_scenario.py')['exercise']()
    root=Path('/fixture')
    for name,mode in (('bridge',0o755),('worker',0o755),('bootstrap',0o755),('lock',0o700),('config',0o700),('ca',0o755),('broker',0o755),('auth-socket',0o755),('source-secrets',0o700),('auth-secrets',0o700)):
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
    def controlled(environ, start_response):
        if (os.environ.get('NETBOX_SYNC_FULL_LIFECYCLE')=='1'
                and (root/'bridge/refuse-creation').exists()
                and environ.get('PATH_INFO','').endswith('/objects/create/')
                and environ.get('REQUEST_METHOD')=='POST'):
            (root/'bridge/creation-refused').touch()
            body=b'{"detail":"isolated transient failure"}'
            start_response('503 Service Unavailable',[('Content-Type','application/json'),('Content-Length',str(len(body)))])
            return [body]
        if (os.environ.get('NETBOX_SYNC_FULL_LIFECYCLE')=='1'
                and (root/'bridge/refuse-retirement').exists()
                and environ.get('PATH_INFO','').endswith('/sources/execute/')
                and environ.get('REQUEST_METHOD')=='POST'):
            body=b'{"code":"GUARD_UNAVAILABLE"}'
            start_response('503 Service Unavailable',[('Content-Type','application/json'),('Content-Length',str(len(body)))])
            return [body]
        return application(environ,start_response)
    server.set_app(controlled)
    # Only the test byte relay mounts this fixture directory. Public TLS remains
    # end-to-end between real worker and NetBox WSGI; relay cannot read payloads.
    (root/'bridge/netbox.sock').chmod(0o666)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    (root/'bridge/ready.json').write_text(json.dumps({'guard_instance':instance,'source':source,'cluster':cluster,'direct_url':direct_url,'catalog_slug':catalog_slug,'vrfs':vrfs}))
    try:
        deadline=time.monotonic()+(1800 if os.environ.get('NETBOX_SYNC_FULL_LIFECYCLE')=='1' else 240)
        applied=set()
        while not (root/'bridge/done.json').exists():
            if os.environ.get('NETBOX_SYNC_FULL_LIFECYCLE')=='1' and (root/'bridge/installation.json').exists():
                # Test setup emulates the external NetBox operator's once-only
                # installation grant. No application endpoint grants itself rights.
                import re
                namespace=json.loads((root/'bridge/installation.json').read_text())['namespace']
                assert re.fullmatch('[a-f0-9]{32}',namespace)
                if namespace not in applied:
                    from users.models import ObjectPermission
                    permission=ObjectPermission.objects.get(pk=permission_id)
                    prior=permission.constraints
                    permission.constraints=(prior if isinstance(prior,list) else [prior])+[{'source_instance__startswith':'n'+namespace+'-'}]
                    permission.save();applied.add(namespace)
                    (root/'bridge/installation-ready.json').write_text(json.dumps({'namespace':namespace}))
            command=root/'bridge/remove-empty-cluster.json'
            ack=root/'bridge/removed-empty-cluster.json'
            if os.environ.get('NETBOX_SYNC_FULL_LIFECYCLE')=='1' and command.exists() and not ack.exists():
                from virtualization.models import Cluster
                from netbox_guard.models import CreationClaim
                request=json.loads(command.read_text())
                assert any(request['source'].startswith('n'+value+'-') for value in applied)
                claim=CreationClaim.objects.get(source_instance=request['source'],resource='cluster')
                target=Cluster.objects.get(pk=claim.object_id)
                assert not target.virtual_machines.exists() and not target.devices.exists()
                identifier=target.pk;target.delete()
                ack.write_text(json.dumps({'cluster':identifier}))
            if time.monotonic()>deadline:raise AssertionError('isolated worker gate did not finish')
            time.sleep(.1)
        assert json.loads((root/'bridge/done.json').read_text())=={'passed':True}
    finally:
        server.shutdown();server.server_close();thread.join(3)
