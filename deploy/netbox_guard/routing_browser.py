"""Human routing inventory, without projecting allocation into address ownership."""
from datetime import datetime
from ipaddress import ip_address, ip_network
from .routing_presentation import KINDS, components, coverage


def data(row):
    return row.get('sections', {}).get(KINDS[row['kind']], {}).get('data') or {}


def matches(row, query):
    if not query:
        return True
    values = data(row)
    if query.casefold() in ' '.join(str(values.get(k, '')) for k in
            ('name', 'vlan', 'zone_name', 'cidr', 'gateway', 'next_hop', 'service_addresses')).casefold():
        return True
    try:
        return ip_address(query) in ip_network(values.get('cidr', ''), strict=False)
    except ValueError:
        return False


def card(row):
    value = data(row)
    section = row['sections'][KINDS[row['kind']]]
    result = dict(key=row['key'], name=value.get('name') or value.get('cidr') or
                  ('VLAN ' + str(value['vlan']) if value.get('vlan') is not None else 'Без названия'),
                  href=row.get('detail_href'), vlan=value.get('vlan'),
                  zone=value.get('zone_name') or '', cidr=value.get('cidr') or '',
                  gateway=value.get('gateway') or '', next_hop=value.get('next_hop') or '',
                  service_addresses=value.get('service_addresses') or [],
                  service={'dedicated': 'Серверы и оборудование', 'cloud': 'Облачная платформа'}.get(value.get('zone_service'), ''),
                  status={'ACTIVE': 'Активен', 'DOWN': 'Неактивен', 'ERROR': 'Ошибка'}.get(value.get('status'), value.get('status') or ''),
                  retained=bool(section.get('retained') or row.get('present_in_latest') is False))
    observed = row.get('last_seen')
    try:
        result['observed'] = datetime.fromisoformat(observed.replace('Z', '+00:00')) if isinstance(observed, str) else observed
    except ValueError:
        result['observed'] = None
    if row['kind'] == 'routing_subnet':
        try:
            subnet = ip_network(result['cidr'], strict=False)
            result.update(mask=str(subnet.netmask), broadcast=str(subnet.broadcast_address) if subnet.version == 4 else '')
        except ValueError:
            pass
    return result


def context(rows, relations, selected, query, snapshot):
    relations = list(relations)
    attached = {child['key'] for router in rows if router['kind'] == 'global_router'
                for child in components(router, rows, relations)}
    scope = components(selected, rows, relations) if selected else rows
    networks = []
    for row in scope:
        if row['kind'] != 'routing_network':
            continue
        children = [r for r in components(row, rows, relations) if r['kind'] == 'routing_subnet']
        if query and not matches(row, query) and not any(matches(r, query) for r in children):
            continue
        value = card(row)
        value['subnets'] = [card(r) for r in children]
        networks.append(value)
    problems = [dict(label=c['label'], message='Сведения получены не полностью' if c['status'] != 'NOT_REPORTED'
                     else 'Сведения ещё не получены') for c in coverage(snapshot) if c['status'] != 'collected']
    return dict(routing_selected=card(selected) if selected else None,
        routing_kind=selected['kind'] if selected else None, routing_query=query,
        routers=[card(r) for r in rows if r['kind'] == 'global_router' and
                 (matches(r, query) or any(matches(c, query) for c in components(r, rows, relations)))],
        networks=sorted(networks, key=lambda n: n['name'].casefold()),
        subnets=[card(r) for r in scope if r['kind'] == 'routing_subnet' and matches(r, query)],
        routes=[card(r) for r in scope if r['kind'] == 'routing_route' and matches(r, query)],
        unlinked=[card(r) for r in rows if r['kind'] in KINDS and r['kind'] != 'global_router'
                  and r['key'] not in attached and matches(r, query)],
        routing_problems=problems)
