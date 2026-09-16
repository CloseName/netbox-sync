"""Read-only auth secret view; writes belong to the networkless secret broker."""
from pathlib import Path
from .secret_broker import SecretBrokerStore
from .tls_config import protected_file
from .local_control import request

AUTH_SECRET_SOCKET = '/run/netbox-sync-auth-secrets/worker.sock'

class AuthSecrets:
    def __init__(self, root='/var/lib/netbox-sync/auth-secrets', socket_path=AUTH_SECRET_SOCKET):
        self.root = Path(root)
        self.socket_path = socket_path

    def create(self, value):
        return request(self.socket_path, {'action':'create','value':value})['result']['key']

    def read(self, key):
        SecretBrokerStore._key(key)
        if not key.startswith('ldap-bind-'):
            raise ValueError('Invalid auth reference')
        return protected_file(self.root/key, 0o600).decode()


def serve_auth_secrets(socket_path, root):
    """Root-peer, create-only capability; cannot read/delete source credentials."""
    import base64
    from uuid import uuid4
    from .local_control import serve, ControlError
    store = SecretBrokerStore(root)
    store.singleton()
    def create(payload):
        if set(payload) != {'action','value'} or payload.get('action') != 'create':
            raise ControlError('CONTROL_REQUEST_INVALID')
        value = payload['value']
        if not isinstance(value,str) or not value or len(value)>4096 or '\x00' in value:
            raise ControlError('CONTROL_REQUEST_INVALID')
        key = 'ldap-bind-' + uuid4().hex
        store.create(uuid4().hex, key, base64.b64encode(value.encode()).decode())
        return {'key':key}
    serve(socket_path, create, allowed_uid=0)
