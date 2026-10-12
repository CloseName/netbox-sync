"""Account-scoped read-only exploration of documented dedicated port endpoints.

No NetBox access, matching decisions, configuration writes, or raw responses on disk.
The auxiliary MAC's role is not documented precisely enough to assert a host NIC.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
from uuid import UUID

from .client import AuditError, Client, read_collection, sanitize
from .collector import Credentials, DEDICATED, stamp


RESOURCE = {'uuid', 'hw_uuid', 'service_type', 'location_uuid', 'project_uuid', 'state'}
PORT = {'uuid', 'hw_uuid', 'port_name', 'port_type', 'port_mode', 'speed',
        'is_enabled', 'is_apply', 'is_processing', 'is_aggregate',
        'aggregate_physical_port_count', 'created', 'updated'}
NETWORK = {'uuid', 'network_type', 'network_assigment_type', 'vlan', 'location_uuid',
           'project_uuid', 'is_processing', 'is_shared'}
AUX = {'asn', 'availability_zone', 'client_ip', 'leaf_pairs', 'loopback_ips',
       'mac_address', 'network_interfaces_ip', 'peer_asn', 'peer_ip', 'peer_name', 'subnet'}
SERVER_TYPES = {'server', 'serverchip', 'custom', 'colocation'}


def identifier(value):
    try:
        return str(UUID(value)) if isinstance(value, str) else None
    except ValueError:
        return None


def fields(value, allowed):
    """Bounded scalar values only; unknown fields and opaque text are excluded."""
    if not isinstance(value, dict):
        return {}
    out = {}
    for key in sorted(allowed & value.keys()):
        item = value[key]
        if item is None or type(item) in (bool, int, float):
            out[key] = item
        elif isinstance(item, str):
            out[key] = ''.join(c for c in item if c.isprintable())[:512]
        elif key in ('leaf_pairs', 'loopback_ips') and isinstance(item, list):
            out[key] = [x[:256] for x in item[:128] if isinstance(x, str)]
    return out


def project_port(value):
    out = fields(value, PORT)
    if 'aux_network_info' in value:
        aux = value['aux_network_info']
        out['aux_network_info'] = fields(aux, AUX) if isinstance(aux, dict) else None
        out['aux_response_shape'] = type(aux).__name__
    if 'network' in value:
        networks = value['network']
        if isinstance(networks, list):
            out['network'] = [fields(n, NETWORK) for n in networks if isinstance(n, dict)]
        else:
            out['network'] = None
    return out


def classify(code, has_data=False):
    if code == 'collected':
        return 'collected' if has_data else 'empty'
    return {'HTTP_401': 'authentication_failed', 'HTTP_403': 'denied',
            'HTTP_404': 'not_found', 'ASYNC_RESPONSE_NOT_COLLECTED': 'pending',
            'HTTP_429': 'rate_limited'}.get(code, 'unavailable')


class PortProbe:
    def __init__(self, credentials, client=None, progress=print):
        self.credentials = credentials
        self.client = client or Client(max_requests=5000)
        self.progress = progress
        self.token = ''
        self.records = []
        self.cache = {}
        self.exhausted = False

    def get(self, path, kind):
        if path in self.cache:
            return self.cache[path]
        record = {'endpoint': path, 'kind': kind, 'observed_at': stamp(), 'data': None}
        try:
            if self.exhausted or len(self.records) >= 4000:
                raise AuditError('REQUEST_BUDGET_EXCEEDED')
            response, _ = self.client.request(DEDICATED + path, self.token)
            response = sanitize(response, self.credentials.secrets)
            if not isinstance(response, dict):
                raise AuditError('UNEXPECTED_RESPONSE_SHAPE')
            if str(response.get('status', '')).lower() in ('error', 'failed', 'failure'):
                raise AuditError('PROVIDER_RESPONSE_ERROR')
            value = response.get('result')
            if kind in ('ports', 'port', 'networks'):
                # Published list examples also show one object. Accept only identifiable objects.
                rows = value if isinstance(value, list) else [value] if isinstance(value, dict) and identifier(value.get('uuid')) else None
                if rows is None or any(not isinstance(r, dict) for r in rows):
                    raise AuditError('UNEXPECTED_RESPONSE_SHAPE')
                if len(rows) > 10000:
                    raise AuditError('ITEM_LIMIT_EXCEEDED')
                record['data'] = [fields(r, NETWORK) if kind == 'networks' else project_port(r) for r in rows]
                # Never silently certify a potentially truncated single-page response.
                total = response.get('total') or response.get('total_count')
                limit = response.get('limit')
                incomplete = (response.get('next') or
                    response.get('links') or response.get('result_links') or
                    (type(total) is int and total > len(rows)) or
                    (type(limit) is int and limit > 0 and len(rows) >= limit))
                record['code'] = 'PAGINATION_UNRESOLVED' if incomplete else 'collected'
                if kind == 'port' and any(identifier(r.get('uuid')) != path.rsplit('/', 1)[-1] for r in rows):
                    record['code'] = 'PORT_RESPONSE_ID_MISMATCH'
            elif not isinstance(value, dict):
                raise AuditError('UNEXPECTED_RESPONSE_SHAPE')
            elif kind == 'auxiliary':
                record['data'] = fields(value, {'uuid', 'location_uuid', 'state'})
                ports = value.get('ports')
                if isinstance(ports, list) and len(ports) <= 10000 and all(isinstance(p, dict) for p in ports):
                    record['data']['ports'] = [project_port(p) for p in ports]
                    record['code'] = 'collected'
                else:
                    record['code'] = 'PORTS_FIELD_MISSING_OR_INVALID'
            else:
                record['data'] = fields(value, RESOURCE)
                record['code'] = 'collected'
            record['response_shape'] = type(value).__name__
        except AuditError as exc:
            record['code'] = str(exc)
            if str(exc) in ('REQUEST_BUDGET_EXCEEDED', 'HTTP_401'):
                self.exhausted = True
        record['status'] = classify(record['code'], bool(record['data']))
        self.records.append(record)
        self.cache[path] = record
        return record

    def run(self):
        if not self.credentials.token:
            raise AuditError('ACCOUNT_IAM_TOKEN_REQUIRED')
        self.token, _ = self.credentials.authenticate(self.client)
        rows, _, code = read_collection(self.client, DEDICATED + '/resource', self.token, 'result', 'page')
        rows = sanitize(rows, self.credentials.secrets)
        resources = [fields(r, RESOURCE) for r in rows if r.get('service_type') in SERVER_TYPES]
        notes, hardware, ports = [], set(), set()
        if len(resources) > 1000:
            resources = resources[:1000]
            notes.append('RESOURCE_LIMIT_REACHED')
        for index, resource in enumerate(resources, 1):
            if self.exhausted:
                break
            rid = identifier(resource.get('uuid'))
            if not rid:
                notes.append('INVALID_RESOURCE_UUID')
                continue
            self.progress(f'Сервер {index}/{len(resources)}: {rid}')
            detail = self.get('/resource/' + rid, 'resource')
            aux = self.get('/resource/' + rid + '/aux_network_info', 'auxiliary')
            # Keep observations separate: a changed hardware identity is a conflict, not a merge.
            known_hw = identifier(resource.get('hw_uuid'))
            detail_data = detail.get('data') or {}
            reported_hw = identifier(detail_data.get('hw_uuid'))
            if detail_data.get('uuid') and detail_data['uuid'] != rid:
                notes.append('RESOURCE_RESPONSE_ID_MISMATCH:' + rid)
                reported_hw = None
            if known_hw and reported_hw and known_hw != reported_hw:
                notes.append('RESOURCE_HARDWARE_CHANGED:' + rid)
            hardware.update(h for h in (known_hw, reported_hw) if h)
            if not known_hw and not reported_hw:
                notes.append('HARDWARE_UUID_NOT_REPORTED:' + rid)
            aux_data = aux.get('data') or {}
            if aux_data.get('uuid') and aux_data['uuid'] != rid:
                notes.append('AUX_RESPONSE_ID_MISMATCH:' + rid)
                continue
            ports.update(p for row in aux_data.get('ports', []) if (p := identifier(row.get('uuid'))))
        for hw in sorted(hardware):
            if self.exhausted:
                break
            result = self.get('/network/port/hw/' + hw, 'ports')
            ports.update(p for row in result.get('data') or [] if (p := identifier(row.get('uuid'))))
        if len(ports) > 2000:
            notes.append('PORT_LIMIT_REACHED')
        for port in sorted(ports)[:2000]:
            if self.exhausted:
                break
            self.get('/network/port/' + port, 'port')
            self.get('/network/port/' + port + '/network', 'networks')
        if self.exhausted:
            notes.append('PROBE_STOPPED_EARLY')
        document = {'schema': 'selectel-port-probe-v1', 'account': self.credentials.account,
                    'finished_at': stamp(), 'mode': 'read_only', 'writes_performed': False,
                    'scope': 'visible_dedicated_resources', 'account_completeness': 'not_proven',
                    'resource_enumeration': {'code': code, 'status': classify(code, bool(rows))},
                    'resources': resources, 'records': self.records, 'notes': sorted(set(notes)),
                    'provider_port_confirmed': False,
                    'limitations': ['AUX_MAC_ROLE_NOT_VERIFIED', 'NO_CABLE_INFERENCE',
                                    'ADMIN_STATE_IS_NOT_LINK_STATE_OR_INTENT', 'NO_NETBOX_ACCESS']}
        return sanitize(document, self.credentials.secrets)


def summarize(document):
    useful = []
    for record in document['records']:
        data = record.get('data')
        ports = data if isinstance(data, list) else (data or {}).get('ports', [])
        for port in ports:
            aux = port.get('aux_network_info')
            if isinstance(aux, dict) and any(v not in (None, '', []) for v in aux.values()):
                useful.append({'endpoint': record['endpoint'], 'port_uuid': port.get('uuid'),
                               'aux_network_info': aux})
    return {'schema': document['schema'], 'account': document['account'],
            'resource_enumeration': document['resource_enumeration'],
            'resource_count': len(document['resources']), 'endpoint_count': len(document['records']),
            'statuses': dict(Counter(r['status'] for r in document['records'])),
            'codes': dict(Counter(r['code'] for r in document['records'])),
            'auxiliary_evidence': useful, 'notes': document['notes'],
            'writes_performed': False, 'provider_port_confirmed': False}


def main():
    from .__main__ import hidden
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', required=True)
    parser.add_argument('--output', default='/output')
    args = parser.parse_args()
    os.umask(0o077)
    credentials = Credentials(args.account, token=hidden('IAM-токен аккаунта (скрытый ввод): '))
    document = PortProbe(credentials).run()
    directory = Path(args.output) / (credentials.account + '-' + stamp().replace(':', '').replace('+', '_'))
    directory.mkdir(parents=True, exist_ok=False)
    summary = summarize(document)
    for name, value in [('ports.json', document), ('summary.json', summary)]:
        (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print('Сохранено: ' + str(directory))
    print('Только чтение. Пришлите summary.json; подробные ответы — ports.json.')


if __name__ == '__main__':
    try:
        main()
    except (AuditError, KeyboardInterrupt, EOFError) as exc:
        print('Проверка остановлена: ' + (str(exc) if isinstance(exc, AuditError) else 'INPUT_CANCELLED'), file=sys.stderr)
        sys.exit(2)
    except Exception:
        print('Проверка остановлена: INTERNAL_ERROR', file=sys.stderr)
        sys.exit(3)
