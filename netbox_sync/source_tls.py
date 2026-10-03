"""Explicit additional source CA trust, independent of NetBox and environment."""
from pathlib import Path
import ssl
from .tls_config import protected_file, validate_ca
from .netbox_tls import configure_session

CA_FILE = Path('/run/netbox-sync-ca/source-ca.pem')


def source_context(verify=True):
    if not verify:
        return ssl._create_unverified_context()
    context = ssl.create_default_context()
    if CA_FILE.exists() or CA_FILE.is_symlink():
        data = protected_file(CA_FILE, 0o644)
        validate_ca(data)
        context.load_verify_locations(cadata=data.decode('ascii'))
    return context


def configure_proxmox(provider, verify=True):
    session = provider._store['session']
    session.trust_env = False
    if verify:
        configure_session(session, CA_FILE)
        # proxmoxer passes auth.verify_ssl explicitly on every request.
        session.auth.verify_ssl = session.verify
    else:
        session.verify = False
        session.auth.verify_ssl = False
    return provider
