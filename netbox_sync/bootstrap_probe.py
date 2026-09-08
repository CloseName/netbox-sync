"""Read-only, bounded NetBox prerequisite probe in an isolated subprocess."""
import json
import socket
import sys
from urllib.parse import urlsplit
import requests
from .api.egress import EgressPolicy, pinned_dns
from .netbox_tls import configure_session
from .tls_config import TLSConfigurationError

FIELDS = {
    'sync_identities': ('json', ('dcim.device','dcim.interface','virtualization.virtualmachine','virtualization.vminterface')),
    'sync_original_names': ('json', ('dcim.device','dcim.interface','virtualization.virtualmachine','virtualization.vminterface')),
    'hypervisor_version': ('text', ('dcim.device',)),
    'cpu_model': ('text', ('dcim.device',)), 'cpu_vendor': ('text', ('dcim.device',)),
    'cpu_sockets': ('integer', ('dcim.device',)), 'cpu_cores': ('integer', ('dcim.device',)),
    'cpu_threads': ('integer', ('dcim.device',)), 'memory_mb': ('integer', ('dcim.device',)),
    'physical_disks': ('json', ('dcim.device',)),
    'guest_kind': ('text', ('virtualization.virtualmachine',)),
    'guest_architecture': ('text', ('virtualization.virtualmachine',)),
    'guest_os_type': ('text', ('virtualization.virtualmachine',)),
    'swap_mb': ('integer', ('virtualization.virtualmachine',)),
    'source_bridge': ('text', ('virtualization.vminterface',)),
    'source_vlan_id': ('integer', ('virtualization.vminterface',)),
}
ENDPOINTS = ('dcim/devices','dcim/interfaces','virtualization/clusters',
             'virtualization/virtual-machines','virtualization/interfaces','ipam/ip-addresses')


class ProbeError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def fetch(session, url, token, method='GET'):
    with session.request(method, url, headers={'Authorization': 'Token ' + token},
                         timeout=(3, 5), allow_redirects=False, stream=True) as response:
        if response.status_code == 401:
            raise ProbeError('AUTH_FAILED')
        if response.status_code == 403:
            raise ProbeError('PERMISSION_DENIED')
        if response.status_code != 200:
            raise ProbeError('RESPONSE_INVALID')
        raw = bytearray()
        for part in response.iter_content(8192):
            raw.extend(part)
            if len(raw) > 2 * 1024 * 1024:
                raise ProbeError('RESPONSE_INVALID')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ProbeError('RESPONSE_INVALID')
        return value


def probe(value, session_factory=requests.Session, policy=None):
    checks = []
    try:
        parsed = urlsplit(value['url'])
        host, address = (policy or EgressPolicy(allowed_hosts=(parsed.hostname,))).resolve(parsed.hostname, parsed.port or 443)
        with pinned_dns(host, address, parsed.port or 443), session_factory() as session:
            configure_session(session)
            for endpoint in ENDPOINTS:
                url = value['url'] + '/api/' + endpoint + '/'
                for kind in ('read', 'apply'):
                    result = fetch(session, url + '?limit=1', value[kind + '_token'])
                    if not isinstance(result.get('results'), list) or type(result.get('count')) is not int:
                        raise ProbeError('RESPONSE_INVALID')
                    metadata = fetch(session, url, value[kind + '_token'], 'OPTIONS')
                    actions = metadata.get('actions', {})
                    if not isinstance(actions, dict):
                        raise ProbeError('RESPONSE_INVALID')
                    if (kind == 'read' and 'POST' in actions) or (kind == 'apply' and 'POST' not in actions):
                        raise ProbeError('PERMISSION_DENIED')
            result = fetch(session, value['url'] + '/api/extras/custom-fields/?limit=1000', value['read_token'])
            rows = result.get('results')
            if not isinstance(rows, list) or result.get('next') is not None:
                raise ProbeError('RESPONSE_INVALID')
            by_name = {row['name']: row for row in rows if isinstance(row, dict) and isinstance(row.get('name'), str)}
            for name, (kind, models) in FIELDS.items():
                row = by_name.get(name, {})
                field_type = row.get('type', {})
                if isinstance(field_type, dict):
                    field_type = field_type.get('value')
                okay = field_type == kind and set(models).issubset(set(row.get('object_types', [])))
                checks.append({'name': name, 'type': kind, 'models': list(models), 'ok': okay})
            return {'safe_code': None if all(check['ok'] for check in checks) else 'PREREQUISITES_MISSING', 'checks': checks}
    except (requests.exceptions.SSLError, TLSConfigurationError):
        code = 'TLS_FAILED'
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, socket.gaierror):
        code = 'NETWORK_UNREACHABLE'
    except ProbeError as error:
        code = error.code
    except Exception as error:
        code = 'DESTINATION_DENIED' if getattr(getattr(error, 'code', None), 'value', '') == 'SOURCE_DESTINATION_DENIED' else 'RESPONSE_INVALID'
    return {'safe_code': code, 'checks': []}


if __name__ == '__main__':
    try:
        value = json.loads(sys.stdin.buffer.read(32769))
        print(json.dumps(probe(value)))
    except Exception:
        print(json.dumps({'safe_code': 'RESPONSE_INVALID', 'checks': []}))
