"""Installation-scoped source names for once-only constrained Guard permissions."""
import re
from uuid import uuid4


def prefix(namespace):
    if not isinstance(namespace, str) or not re.fullmatch('[a-f0-9]{32}', namespace):
        raise ValueError('Invalid installation namespace')
    return 'n' + namespace + '-'


def new_source(provider, namespace=''):
    if provider not in ('esxi','proxmox'):
        raise ValueError('Invalid provider')
    return (prefix(namespace) if namespace else '') + provider + '-' + uuid4().hex[:20]


def belongs(source, namespace):
    return isinstance(source, str) and source.startswith(prefix(namespace))
