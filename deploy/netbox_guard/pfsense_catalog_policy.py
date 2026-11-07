"""Stable configuration identity and bounded, appliance-local reference search."""
from hashlib import sha256
from ipaddress import ip_address, ip_interface, ip_network
import json
import re

CATEGORIES = {'general': 'system', 'users': 'system', 'certificates': 'system', 'firewall': 'rules', 'nat': 'nat', 'aliases': 'aliases', 'routing': 'routes',
              'openvpn': 'vpn', 'ipsec': 'vpn', 'wireguard': 'vpn'}
TABS = [('overview', 'Обзор'), ('system', 'System'), ('interfaces', 'Интерфейсы и сети'), ('rules', 'Правила'),
        ('nat', 'NAT'), ('aliases', 'Aliases'), ('routes', 'Маршруты'), ('vpn', 'VPN'), ('services', 'Сервисы')]
FIELD_LABELS = {'source/address': 'Источник', 'source/network': 'Сеть источника',
                'destination/address': 'Назначение', 'destination/network': 'Сеть назначения',
                'address': 'Адрес', 'network': 'Сеть', 'target': 'Адрес NAT', 'targetip': 'Адрес NAT',
                'external': 'Внешний адрес', 'gateway': 'Шлюз', 'port': 'Порт',
                'source/port': 'Порт источника', 'destination/port': 'Порт назначения',
                'parent': 'Родительский интерфейс', 'tag': 'VLAN ID', 'mtu': 'MTU', 'mac': 'MAC'}


ALIAS_FIELDS = {'source/address', 'destination/address', 'source/port', 'destination/port',
                'address', 'network', 'target', 'external', 'port', 'local-port', 'natport'}


def identity_fields(component, row):
    # Empty fields introduced by newer collectors must preserve existing content IDs.
    additions = {'firewall': {'defaultqueue', 'ackqueue', 'associated-rule-id'}, 'nat': {'nordr'}}
    return {k: v for k, v in row.items() if k != 'order' and (v or k not in additions.get(component, ()))}


def identity(component, table, row):
    # Never use rule position as identity. Anonymous entries have content identity:
    # edits create a new object, whereas a reorder preserves its UUID.
    keys = ('tracker',) if component == 'firewall' else ('name', 'vpnid', 'ikeid', 'uniqid')
    if component in ('certificates', 'users'):
        keys = ('refid', 'uid', 'gid', 'name')
    native = next(((key, row[key]) for key in keys if row.get(key) and row[key] != ['']), None)
    if (component, table) in {('general', 'settings'), ('general', 'webgui'), ('users', 'settings')}:
        native = ('singleton', [table])
    basis = native or identity_fields(component, row)
    digest = sha256(json.dumps([component, table, basis], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return digest, 'native' if native else 'content'


def enabled(row):
    def truth(values):
        return bool(values) and values != ['no'] and values != ['false'] and values != ['0']
    if truth(row.get('disabled')) or truth(row.get('disable')):
        return False
    for key in ('enabled', 'enable'):
        if key in row:
            return truth(row[key])
    return True


def title(row, fallback):
    return next((' · '.join(row[k]) for k in ('name', 'descr', 'description', 'tracker', 'network', 'hostname', 'host', 'address', 'refid', 'serial')
                 if row.get(k) and row[k] != ['']), fallback)[:256]


def tokens(values):
    return [v for value in values if isinstance(value, str) for v in re.split(r'[\s,]+', value) if v]


def contains(query, value):
    try:
        requested = ip_network(query, strict=False)
    except ValueError:
        return False
    try:
        candidate = ip_network(value, strict=False)
        return requested.version == candidate.version and requested.subnet_of(candidate)
    except ValueError:
        pass
    if '-' in value and '/' not in query:
        try:
            first, last = (ip_address(v) for v in value.split('-', 1))
            address = ip_address(query)
            return first.version == last.version == address.version and first <= address <= last
        except ValueError:
            pass
    return False


def alias_paths(name, aliases, query):
    pending, visited, found = [(name, [name])], set(), []
    while pending and len(visited) < 4096:
        current, path = pending.pop()
        if current in visited or len(path) > 32:
            continue
        visited.add(current)
        for item in tokens(aliases.get(current, [])):
            if contains(query, item) or query.casefold() == item.casefold() or port_contains(query, item):
                found.append(' → '.join(path + [item]))
            if item in aliases:
                pending.append((item, path + [item]))
    return found[:5]


def port_contains(query, value):
    if query.isdigit() and re.fullmatch(r'\d+[:-]\d+', value):
        start, end = map(int, re.split('[:-]', value))
        return 0 <= start <= int(query) <= end <= 65535
    return False


def rule_groups(row):
    if row.get('floating') in ([''], ['yes'], ['true'], ['1']):
        return ['__floating__']
    return list(dict.fromkeys(tokens(row.get('interface', []))))


def search_hits(query, row, aliases, interface=False):
    query = query.strip()
    if not query:
        return []
    try:
        ip_network(query, strict=False)
        typed = True
    except ValueError:
        typed = False
    hits = {}
    def record(field, token, label, path=''):
        covering = False
        description = token
        if typed:
            try:
                candidate = ip_interface(token)
                if interface and field == 'address' and '/' not in query:
                    if ip_address(query) != candidate.ip:
                        return
                else:
                    covering = ip_network(query, strict=False) != candidate.network
                    if covering and candidate.ip != candidate.network.network_address:
                        description += ' (сеть ' + str(candidate.network) + ')'
            except ValueError:
                covering = '-' in token
        if field.startswith(('source/', 'destination/')) and row.get(field.split('/')[0] + '/not'):
            label += ' (исключение)'
        reason = label + ((' · alias ' + path + ' → ') if path else ': ') + description
        hits[reason] = dict(reason=reason, covering=covering)

    for field, values in row.items():
        if field == 'order' or not isinstance(values, list):
            continue
        label = FIELD_LABELS.get(field, field)
        searchable = tokens(values) if field in ALIAS_FIELDS else values
        for value in searchable:
            if not typed and query.casefold() in value.casefold():
                record(field, value, label)
        for token in tokens(values):
            if typed and contains(query, token):
                record(field, token, label)
            if token in aliases and field in ALIAS_FIELDS:
                for path in alias_paths(token, aliases, query):
                    chain, _, terminal = path.rpartition(' → ')
                    record(field, terminal, label, chain)
            if 'port' in field and port_contains(query, token):
                record(field, token, label)
    return sorted(hits.values(), key=lambda hit: hit['covering'])[:8]


def match(query, row, aliases):
    return [hit['reason'] for hit in search_hits(query, row, aliases)]
