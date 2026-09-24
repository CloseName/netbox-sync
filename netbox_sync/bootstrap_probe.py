"""Read-only, bounded NetBox prerequisite probe in an isolated subprocess."""
import json
import socket
import sys
from urllib.parse import urlsplit
import requests
from .api.egress import EgressPolicy, pinned_dns
from .netbox_tls import configure_session
from .tls_config import TLSConfigurationError

from .prerequisites import FIELDS, reconcile
from .netbox_auth import authorization

ENDPOINTS = ('dcim/devices','dcim/interfaces','virtualization/clusters',
             'virtualization/virtual-machines','virtualization/interfaces','ipam/ip-addresses')


class ProbeError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ObjectNotVisible(ProbeError):
    def __init__(self):
        super().__init__('RESPONSE_INVALID')


def fetch(session, url, token, method='GET'):
    with session.request(method, url, headers={'Authorization': authorization(token)},
                         timeout=(3, 5), allow_redirects=False, stream=True) as response:
        if response.status_code == 401:
            raise ProbeError('AUTH_FAILED')
        if response.status_code == 403:
            raise ProbeError('PERMISSION_DENIED')
        if response.status_code == 404:
            raise ObjectNotVisible()
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
    access = {name:'not_run' for name in ('network','tls','read_auth','apply_auth','permissions','prerequisites','guard')}
    kind = 'read'
    def evidence():return [{'name': name, 'status': status} for name,status in access.items()]
    try:
        parsed = urlsplit(value['url'])
        host, address = (policy or EgressPolicy(allowed_hosts=(parsed.hostname,))).resolve(parsed.hostname, parsed.port or 443)
        access['network'] = 'passed'
        with pinned_dns(host, address, parsed.port or 443), session_factory() as session:
            configure_session(session)
            for endpoint in ENDPOINTS:
                url = value['url'] + '/api/' + endpoint + '/'
                for kind in ('read', 'apply'):
                    result = fetch(session, url + '?limit=1', value[kind + '_token'])
                    access['tls'] = 'passed'
                    access[kind+'_auth'] = 'passed'
                    if not isinstance(result.get('results'), list) or type(result.get('count')) is not int:
                        raise ProbeError('RESPONSE_INVALID')
                    metadata = fetch(session, url, value[kind + '_token'], 'OPTIONS')
                    actions = metadata.get('actions', {})
                    if not isinstance(actions, dict):
                        raise ProbeError('RESPONSE_INVALID')
                    if (kind == 'read' and 'POST' in actions) or (kind == 'apply' and 'POST' not in actions):
                        raise ProbeError('PERMISSION_DENIED')
            access['permissions'] = 'preliminary'
            if value.get('guard_instance'):
                from .retirement_transport import GuardClient,GuardTransportError
                try:
                    guard=GuardClient(session,value['url'],authorization(value['apply_token']),value['guard_instance'])
                    capabilities=guard.capabilities()
                    if capabilities.get('source_audit') is not True:raise GuardTransportError('GUARD_CAPABILITY_MISMATCH')
                    if capabilities.get('audit_permission') is not True:raise GuardTransportError('GUARD_AUDIT_PERMISSION_REQUIRED')
                    if capabilities.get('token_write_enabled') is not True:raise GuardTransportError('TOKEN_WRITE_REQUIRED')
                    access['guard']='preliminary' # source/object restrictions require an actual scoped audit
                except GuardTransportError as exc:
                    access['guard']='failed'
                    raise ProbeError({'AUTHENTICATION_REQUIRED':'AUTH_FAILED','TOKEN_WRITE_REQUIRED':'RETIREMENT_TOKEN_WRITE_REQUIRED',
                        'GUARD_AUDIT_PERMISSION_REQUIRED':'RETIREMENT_AUDIT_PERMISSION_REQUIRED','PERMISSION_DENIED':'PERMISSION_DENIED',
                        'GUARD_TLS_FAILED':'TLS_FAILED','GUARD_CONNECTION_FAILED':'NETWORK_UNREACHABLE','GUARD_TIMEOUT':'NETWORK_UNREACHABLE'
                        }.get(exc.code,'RETIREMENT_GUARD_CHANGED')) from None

            kind = 'read'
            result = fetch(session, value['url'] + '/api/extras/custom-fields/?limit=1000', value['read_token'])
            rows = result.get('results')
            if not isinstance(rows, list) or result.get('next') is not None:
                raise ProbeError('RESPONSE_INVALID')
            fields = reconcile(rows)
            checks = [{'name': f['name'], 'type': f['type'], 'models': f['models'], 'ok': f['status']=='ready'} for f in fields]
            access['prerequisites'] = 'passed' if all(c['ok'] for c in checks) else 'pending'
            return {'safe_code': None if all(check['ok'] for check in checks) else 'PREREQUISITES_MISSING', 'checks': checks, 'access_checks': evidence()}
    except (requests.exceptions.SSLError, TLSConfigurationError):
        code = 'TLS_FAILED'
        access['tls'] = 'failed'
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, socket.gaierror):
        code = 'NETWORK_UNREACHABLE'
        access['network'] = 'failed'
    except ProbeError as error:
        code = error.code
        if code=='AUTH_FAILED':access[kind+'_auth']='failed'
        if code=='PERMISSION_DENIED':access['permissions']='failed'
    except Exception as error:
        code = 'DESTINATION_DENIED' if getattr(getattr(error, 'code', None), 'value', '') == 'SOURCE_DESTINATION_DENIED' else 'RESPONSE_INVALID'
    return {'safe_code': code, 'checks': [], 'access_checks': evidence()}


if __name__ == '__main__':
    try:
        value = json.loads(sys.stdin.buffer.read(32769))
        print(json.dumps(probe(value)))
    except Exception:
        print(json.dumps({'safe_code': 'RESPONSE_INVALID', 'checks': []}))
