"""Real local TLS checks for source trust and proxmoxer request behavior."""
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
import requests
from proxmoxer import ProxmoxAPI
from tests.tls_fixture import create_certificates
from netbox_sync import source_tls
from netbox_sync.api.egress import pinned_dns
from netbox_sync.tls_config import TLSConfigurationError

@pytest.fixture
def endpoint(tmp_path, monkeypatch):
    certs = create_certificates(tmp_path / 'certs')
    monkeypatch.setattr(source_tls, 'CA_FILE', certs / 'ca.pem')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            body = json.dumps({'data': {'version': 'test'}}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certs / 'fullchain.pem', certs / 'privkey.pem')
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port, certs
    server.shutdown(); server.server_close(); thread.join()


def test_probe_context_accepts_ca_but_rejects_wrong_hostname(endpoint):
    import socket
    port, _ = endpoint
    for name, valid in [('netbox.example.test', True), ('wrong.example.test', False)]:
        def connect():
            with socket.create_connection(('127.0.0.1', port)) as sock:
                with source_tls.source_context().wrap_socket(sock, server_hostname=name): pass
        if valid: connect()
        else:
            with pytest.raises(ssl.SSLCertVerificationError): connect()


def test_proxmox_requests_use_bundle_ignore_proxy_and_check_hostname(endpoint, monkeypatch):
    port, _ = endpoint
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('REQUESTS_CA_BUNDLE', '/invalid/environment-ca')
    for name, valid in [('netbox.example.test', True), ('wrong.example.test', False)]:
        api = ProxmoxAPI(name, port=port, user='test@pve', token_name='test', token_value='test')
        source_tls.configure_proxmox(api)
        with pinned_dns(name, '127.0.0.1', port):
            if valid: assert api.version.get() == {'version': 'test'}
            else:
                with pytest.raises(requests.exceptions.SSLError): api.version.get()


def test_missing_and_invalid_ca_fail_closed(endpoint, monkeypatch, tmp_path):
    port, _ = endpoint
    monkeypatch.setattr(source_tls, 'CA_FILE', tmp_path / 'missing')
    api = ProxmoxAPI('netbox.example.test', port=port, user='test@pve', token_name='test', token_value='test')
    source_tls.configure_proxmox(api)
    with pinned_dns('netbox.example.test', '127.0.0.1', port):
        with pytest.raises(requests.exceptions.SSLError): api.version.get()
    source_tls.CA_FILE.write_text('invalid CA')
    source_tls.CA_FILE.chmod(0o644)
    with pytest.raises(TLSConfigurationError): source_tls.source_context()
    with pytest.raises(TLSConfigurationError): source_tls.configure_proxmox(api)


def test_explicit_insecure_mode_remains_explicit(monkeypatch, tmp_path):
    monkeypatch.setattr(source_tls, 'CA_FILE', tmp_path / 'missing')
    assert source_tls.source_context(False).verify_mode == ssl.CERT_NONE
    api = ProxmoxAPI('example.test', user='test@pve', token_name='test', token_value='test', verify_ssl=False)
    source_tls.configure_proxmox(api, False)
    assert api._store['session'].auth.verify_ssl is False
    assert api._store['session'].trust_env is False


def test_probe_mount_and_restore_contract():
    root = Path(__file__).parents[1]
    compose = (root / 'compose.production.yml').read_text()
    probe = compose.split('  netbox-sync-probe-worker:', 1)[1].split('  netbox-sync-secret-broker:', 1)[0]
    assert '/run/netbox-sync-ca:ro' in probe


def test_source_ca_restore_permissions_and_error_classification():
    from deploy import backup
    from netbox_sync.api.connection_probe import classify
    from netbox_sync.application.observability import ErrorCode
    assert backup._persistent_permissions('secrets/ca/source-ca.pem') == (0o644, 0)
    assert classify(TLSConfigurationError('invalid')) == ErrorCode.SOURCE_TLS_FAILED
