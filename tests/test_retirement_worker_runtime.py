"""Container-only real UDS/child/HTTPS test. Endpoint is a protocol fixture.

Invoke ONLY in an ephemeral Docker container, no host /run mount. A missing
Docker marker or explicit test flag skips before any fixture writes/processes.
Real NetBox atomicity/ownership is covered separately by the NetBox model gates.
"""
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4
import pytest

ISOLATED = (os.name == 'posix' and Path('/.dockerenv').is_file()
            and os.environ.get('NETBOX_SYNC_RETIREMENT_RUNTIME_TEST') == '1')
pytestmark = pytest.mark.skipif(not ISOLATED, reason='requires explicit isolated Docker fixture')


def test_real_private_worker_transport_and_lost_response(tmp_path):
    assert ISOLATED and Path('/.dockerenv').is_file() and os.getuid() == 0
    from netbox_sync.local_control import ControlError
    from netbox_sync.retirement_worker import RetirementClient
    import ipaddress
    address = socket.gethostbyname(socket.gethostname())
    assert ipaddress.ip_address(address).is_private and not ipaddress.ip_address(address).is_loopback
    instance, operation = str(uuid4()), str(uuid4())
    source = 'esxi-retirement-runtime'
    secret = secrets.token_hex(24)
    calls = []
    state = {'lose': False, 'done': False}
    receipt = {'nonce': operation, 'source_instance': source, 'status': 'REVIEWED',
               'digest': 'a'*64, 'manifest': {'format': 2, 'cluster_id': 5,
               'objects': [['vm:7', 'b'*64]], 'roots': [['vm', 7]]}, 'deleted': []}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def do_GET(self): self.dispatch()
        def do_POST(self): self.dispatch()
        def dispatch(self):
            assert self.headers.get('Authorization') == 'Token ' + secret
            calls.append((self.command, self.path))
            if self.path.endswith('capabilities/'):
                result = {'protocol': 1, 'guard_instance': instance, 'netbox_version': '4.7.0',
                          'atomic_dependency_guard': True, 'creation_receipts': True,
                          'retirement_receipts': True, 'source_tree_retirement': True}
            else:
                assert self.headers.get('X-Netbox-Sync-Guard-Instance') == instance
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))) or '{}')
                if self.path.endswith('sources/execute/'):
                    assert body == {'nonce': operation, 'digest': 'a'*64}
                    state['done'] = True
                    if state['lose']:
                        self.close_connection = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        return
                result = {**receipt, **({'status': 'SUCCEEDED', 'deleted': ['vm:7']} if state['done'] else {})}
            raw = json.dumps(result).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    # Only this disposable container's filesystem; no /run bind mount is allowed.
    mounts = Path('/proc/self/mountinfo').read_text()
    assert not any(line.split()[4].startswith('/run') for line in mounts.splitlines())
    ca = Path('/run/netbox-sync-ca'); ca.mkdir(mode=0o755)
    cert = ca / 'netbox-ca.pem'
    private = tmp_path / 'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
        '-subj','/CN=isolated-retirement','-addext',f'subjectAltName=IP:{address}',
        '-addext','basicConstraints=critical,CA:TRUE','-keyout',str(private),'-out',str(cert)],
        check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
    private.chmod(0o600); cert.chmod(0o644)
    server = ThreadingHTTPServer(('0.0.0.0', 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.load_cert_chain(cert, private)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    config = tmp_path / 'bootstrap.json'; config.touch(mode=0o600)
    config.write_text(json.dumps({'format': 1, 'status': 'READY', 'url': f'https://{address}:{server.server_port}',
                                 'apply_token': secret}), encoding='utf-8')
    sock = tmp_path / 'control' / 'worker.sock'
    env = {**os.environ, 'NETBOX_SYNC_GUARD_INSTANCE': instance,
           'NETBOX_SYNC_NETBOX_CONFIG_FILE': str(config), 'NETBOX_SYNC_RETIREMENT_SOCKET': str(sock)}
    process = subprocess.Popen([sys.executable, '-B', '-m', 'netbox_sync.retirement_worker'],
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic()+10
        while not sock.exists() and process.poll() is None and time.monotonic()<deadline: time.sleep(.05)
        assert sock.exists() and process.poll() is None
        assert sock.stat().st_mode & 0o777 == 0o660
        assert sock.stat().st_uid == 0 and sock.stat().st_gid == 0
        client = RetirementClient(str(sock))
        reviewed = client.call('review', operation, source_instance=source, cluster_id=5)
        assert reviewed == {'guard_instance': instance, 'result': receipt}
        state['lose'] = True
        with pytest.raises(ControlError, match='RETIREMENT_UNCERTAIN'):
            client.call('execute', operation, digest='a'*64)
        assert sum(path.endswith('sources/execute/') for _, path in calls) == 1
        recovered = client.call('receipt', operation)
        assert recovered['result']['status'] == 'SUCCEEDED'
        assert sum(path.endswith('sources/execute/') for _, path in calls) == 1
        with pytest.raises(ControlError, match='CONTROL_REQUEST_INVALID'):
            client.call('execute', operation, digest='invalid')
        assert sum(path.endswith('sources/execute/') for _, path in calls) == 1
    finally:
        process.terminate()
        try: stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); stdout, stderr = process.communicate(timeout=2)
        assert secret.encode() not in stdout+stderr
        server.shutdown(); server.server_close(); thread.join(3)
        cert.unlink(); ca.rmdir()
