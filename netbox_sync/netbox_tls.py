"""Explicit NetBox-only additional CA trust; never inherit proxy/CA environment."""
from pathlib import Path
import tempfile
import weakref
import requests
from .tls_config import protected_file, validate_ca

CA_FILE=Path('/run/netbox-sync-ca/netbox-ca.pem')


def configure_session(session, ca_file=None):
    session.trust_env=False
    session.verify=True
    path=Path(ca_file) if ca_file is not None else CA_FILE
    # Only an absent configured file permits system trust. Broken links and invalid
    # contents fail closed instead of silently ignoring an intended private CA.
    if not path.exists() and not path.is_symlink():return session
    data=protected_file(path,0o644)
    validate_ca(data)
    directory=tempfile.TemporaryDirectory(prefix='netbox-sync-ca-')
    bundle=Path(directory.name)/'bundle.pem'
    bundle.write_bytes(Path(requests.certs.where()).read_bytes()+b'\n'+data+b'\n')
    bundle.chmod(0o600)
    session.verify=str(bundle)
    # Keep the combined bundle alive for this client's entire lifetime only.
    weakref.finalize(session,directory.cleanup)
    session._netbox_ca_directory=directory
    return session
