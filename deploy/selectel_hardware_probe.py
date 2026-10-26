"""Bounded single-server Selectel metadata probe. No import or account-state writes."""
import json
import os
from pathlib import Path
import re
import stat
from uuid import UUID

FIELDS = {'serial': 'system_serial', 'service_tag': 'service_tag', 'system_uuid': 'system_uuid'}
ALIASES = {**FIELDS, 'serial_number': 'system_serial', 'serialNumber': 'system_serial',
           'system_serial': 'system_serial', 'serviceTag': 'service_tag', 'systemUUID': 'system_uuid'}
CONTAINERS = {'system', 'hardware', 'config', 'board', 'chassis', 'case', 'disk',
              'cpu', 'ram', 'bios', 'dmi', 'smbios', 'server'}
MARKER = 'SELECTEL_POINT_PROBE:'


def validate(account, resource):
    if not re.fullmatch(r'[0-9]{1,20}', account) or str(UUID(resource)) != resource:
        raise ValueError('INVALID_SELECTION')


def field_state(kind, value):
    """Explain the installed validator using fixed labels, never the identifier."""
    from netbox_sync.hardware_identity import canonical, PLACEHOLDERS
    if value is None:
        return 'null'
    if not isinstance(value, str):
        return 'wrong_type'
    if canonical(kind, value):
        return 'valid_format'
    value = value.strip()
    if not value:
        return 'empty'
    if len(value) > 256:
        return 'too_long'
    if not value.isprintable():
        return 'nonprintable'
    if value.casefold() in PLACEHOLDERS:
        return 'placeholder'
    compact = value.replace('-', '').replace(' ', '').casefold()
    if not compact or set(compact) <= {'0'} or set(compact) <= {'f'} or compact in {'123456789', '0123456789'}:
        return 'placeholder_pattern'
    return 'invalid_uuid' if kind == 'system_uuid' else 'validator_rejected'


def project(raw, secrets):
    """Inspect fixed field paths only; aliases/components are not matching evidence."""
    from tools.selectel_audit.client import sanitize
    safe = sanitize(raw, secrets)
    roots = {key: {'raw': field_state(kind, raw[key]) if key in raw else 'missing',
                   'after_sanitization': field_state(kind, safe[key]) if key in safe else 'missing',
                   'sanitization_changed': key in raw and raw[key] != safe[key]}
             for key, kind in FIELDS.items()}
    paths = {}
    remaining = 2000
    def walk(value, path='', depth=0):
        nonlocal remaining
        if remaining <= 0 or depth > 6:
            return
        remaining -= 1
        if isinstance(value, list):
            for item in value[:100]:
                walk(item, path + '[]', depth + 1)
        elif isinstance(value, dict):
            for key in sorted(ALIASES.keys() | CONTAINERS):
                if key not in value:
                    continue
                child = path + ('.' if path else '') + key
                if key in ALIASES:
                    paths.setdefault(child, set()).add(field_state(ALIASES[key], value[key]))
                elif key in CONTAINERS:
                    walk(value[key], child, depth + 1)
    walk(raw)
    return {'root_fields': roots, 'candidate_paths': {k: sorted(v) for k, v in paths.items()},
            'path_scan_scope': 'allowlisted_paths_depth6_lists100_nodes2000',
            'aliases_and_components_not_used_for_matching': True}


def collect(account, resource, username, password, client=None):
    from tools.selectel_audit.client import Client, AuditError, read_collection
    from tools.selectel_audit.collector import Credentials, DEDICATED
    validate(account, resource)
    client = client or Client(max_requests=8)
    credential = Credentials(account, username=username, password=password)
    token, _ = credential.authenticate(client)
    rows, _, status = read_collection(client, DEDICATED + '/resource', token, 'result', 'page', max_pages=2)
    if status != 'collected':
        raise AuditError('RESOURCE_LIST_INCOMPLETE')
    selected = [row for row in rows if row.get('uuid') == resource]
    if len(selected) != 1:
        raise AuditError('RESOURCE_NOT_UNIQUE_OR_NOT_VISIBLE')
    service = selected[0].get('service_type')
    if service not in ('server', 'serverchip', 'custom', 'colocation'):
        raise AuditError('UNSUPPORTED_RESOURCE_TYPE')
    sections = {'resource': project(selected[0], credential.secrets)}
    for name, suffix in (('details', ''), ('hardware', '/info/' + service)):
        data, _ = client.request(DEDICATED + '/resource/' + resource + suffix, token)
        if not isinstance(data, dict) or not isinstance(data.get('result'), dict):
            raise AuditError('UNEXPECTED_RESPONSE_SHAPE')
        sections[name] = project(data['result'], credential.secrets)
    return {'account': account, 'resource': resource, 'writes_performed': False,
            'scope': 'live_provider_metadata_only', 'account_scope_verified': True,
            'service_type': service, 'sections': sections,
            'normalizer_projection': 'only_root_serial_service_tag_system_uuid_are_identity_inputs'}


def container_main(account, resource):
    """Read saved credentials privately, then discard privileges before any network I/O."""
    from netbox_sync.selectel_control import read
    from netbox_sync.discovery_worker import _drop_privileges
    from tools.selectel_audit.client import AuditError
    validate(account, resource)
    try:
        base = Path(os.environ.get('NETBOX_SYNC_NETBOX_STATE_DIR', '/var/lib/netbox-sync/netbox'))
        for directory in (base, base / 'selectel'):
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError('INVALID_PRIVATE_DIRECTORY')
        state = read(base / 'selectel' / (account + '.json'))
        if state.get('account') != account or state.get('status') == 'running' or state.get('lifecycle_pending'):
            raise ValueError('ACCOUNT_UNAVAILABLE')
        username, password = state['username'], state['password']
        if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
            raise ValueError('CREDENTIALS_UNAVAILABLE')
        del state
        _drop_privileges(10001, 10001)()
        result = collect(account, resource, username, password)
    except Exception as exc:
        code = str(exc) if isinstance(exc, AuditError) else ''
        allowed = {'HTTP_401', 'HTTP_403', 'HTTP_404', 'TLS_CERTIFICATE_FAILED', 'CONNECTION_FAILED',
                   'ACCOUNT_SCOPE_MISMATCH_USE_ACCOUNT_IAM_TOKEN', 'INVALID_AUTH_RESPONSE',
                   'REQUEST_BUDGET_EXCEEDED', 'RESOURCE_LIST_INCOMPLETE', 'RESOURCE_NOT_UNIQUE_OR_NOT_VISIBLE',
                   'UNSUPPORTED_RESOURCE_TYPE', 'UNEXPECTED_RESPONSE_SHAPE', 'RESPONSE_TOO_LARGE'}
        result = {'account': account, 'resource': resource, 'writes_performed': False,
                  'error': code if code in allowed else 'PROBE_FAILED'}
    print(MARKER + json.dumps(result))


def report(run, account, resource):
    validate(account, resource)
    program = Path(__file__).read_text(encoding='utf-8')
    program += '\ncontainer_main(' + repr(account) + ', ' + repr(resource) + ')\n'
    output = run('docker', 'exec', 'netbox-sync-bootstrap-worker', 'python', '-B', '-c', program)
    if len(output.encode()) > 65536 or not output.startswith(MARKER):
        raise ValueError('PROBE_OUTPUT_INVALID')
    result = json.loads(output[len(MARKER):])
    if result.get('account') != account or result.get('resource') != resource or result.get('writes_performed') is not False:
        raise ValueError('PROBE_OUTPUT_INVALID')
    return result
