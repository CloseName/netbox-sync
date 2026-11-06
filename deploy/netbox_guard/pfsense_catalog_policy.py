"""Stable configuration identity and bounded, appliance-local reference search."""
from hashlib import sha256
from ipaddress import ip_address, ip_network
import json
import re

CATEGORIES = {'firewall': 'rules', 'nat': 'nat', 'aliases': 'aliases', 'routing': 'routes',
              'openvpn': 'vpn', 'ipsec': 'vpn', 'wireguard': 'vpn'}
TABS = [('overview', 'Обзор'), ('interfaces', 'Интерфейсы и сети'), ('rules', 'Правила'),
        ('nat', 'NAT'), ('aliases', 'Aliases'), ('routes', 'Маршруты'), ('vpn', 'VPN'), ('services', 'Сервисы')]
FIELD_LABELS = {'source/address': 'Источник', 'source/network': 'Сеть источника',
                'destination/address': 'Назначение', 'destination/network': 'Сеть назначения',
                'address': 'Адрес', 'network': 'Сеть', 'target': 'Адрес NAT', 'targetip': 'Адрес NAT',
                'external': 'Внешний адрес', 'gateway': 'Шлюз', 'port': 'Порт',
                'source/port': 'Порт источника', 'destination/port': 'Порт назначения',
                'parent': 'Родительский интерфейс', 'tag': 'VLAN ID', 'mtu': 'MTU', 'mac': 'MAC'}


def identity(component, table, row):
    # Never use rule position as identity. Anonymous entries have content identity:
    # edits create a new object, whereas a reorder preserves its UUID.
    keys = ('tracker',) if component == 'firewall' else ('name', 'vpnid', 'ikeid', 'uniqid')
    native = next(((key, row[key]) for key in keys if row.get(key) and row[key] != ['']), None)
    basis = native or {k: v for k, v in row.items() if k != 'order'}
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
    return next((' · '.join(row[k]) for k in ('name', 'descr', 'description', 'tracker', 'network')
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


def match(query, row, aliases):
    query = query.strip()
    if not query:
        return []
    try:
        ip_network(query, strict=False)
        typed = True
    except ValueError:
        typed = False
    reasons = []
    for field, values in row.items():
        if field == 'order' or not isinstance(values, list):
            continue
        label = FIELD_LABELS.get(field, field)
        for value in values:
            if not typed and query.casefold() in value.casefold():
                reasons.append(label + ': ' + value)
        for token in tokens(values):
            if typed and contains(query, token):
                reasons.append(label + ': ' + token)
            if token in aliases and field not in ('name', 'descr', 'description'):
                reasons.extend(label + ' · alias ' + path for path in alias_paths(token, aliases, query))
            if 'port' in field and port_contains(query, token):
                reasons.append(label + ': ' + token)
    return list(dict.fromkeys(reasons))[:8]
