"""Versioned, read-only subnet projection. No Prefix/VRF creation is needed.

A context is a firewall VM + exact interface binding + observed CIDR. Never
merge contexts just because their labels, MACs or addresses happen to match.
"""
from ipaddress import ip_interface, ip_network, ip_address
from .ipam_availability import ranges, freshness


def discovered_networks(vm_id, network_snapshot, inventory, interfaces):
    if not isinstance(network_snapshot, dict) or not isinstance(inventory, dict):
        return []
    result = []
    rows = network_snapshot.get('interfaces')
    if not isinstance(rows, list): return []
    malformed = False
    for row in rows:
        try:
            config, runtime, match = row['configuration'], row['runtime'], row['match']
            current = interfaces.get(match['id'])
            valid = bool(current and current['vm_id'] == vm_id and current.get('mac')
                         and current['mac'].lower() == runtime['mac'].lower())
            networks = {}
            for raw in runtime['addresses']:
                parsed = ip_interface(raw['address'])
                if parsed.ip.is_link_local or parsed.ip.is_loopback: continue
                networks.setdefault(str(parsed.network), []).append(str(parsed))
            for cidr, addresses in networks.items():
                net = ip_network(cidr)
                observation = inventory.get('ipam') or {}
                stamp = inventory.get('collected_at')
                complete = all(observation.get(k) == 'ok' for k in ('configuration','leases','arp'))
                fresh = valid and freshness(stamp, observation.get('interval_seconds'), complete)
                # DHCP/ARP evidence is currently IPv4 only.
                fresh = fresh and net.version == 4
                evidence = [dict(start=str(ip_interface(a).ip),state='gateway',owner='pfSense') for a in addresses]
                for item in observation.get('entries', []):
                    if item.get('interface') not in ('',config['id'],config['device']): continue
                    kind = item.get('kind')
                    state = {'dhcp':'dhcp','static':'reserved','vip':'gateway','lease':'observed','arp':'observed','historical':'observed'}.get(kind)
                    if state:
                        evidence.append(dict(start=item['start'],end=item['end'],state=state,
                            owner=kind+(' · '+item['mac'] if item.get('mac') else '')))
                result.append(dict(id=f"pfsense:{vm_id}:{config['id']}:{cidr}",vm_id=vm_id,
                    interface_id=match['id'],key=config['id'],name=config['name'],cidr=cidr,
                    addresses=addresses,start=str(net.network_address),end=str(net.broadcast_address),
                    collected_at=stamp,fresh=fresh,evidence=evidence,
                    limitations=[] if fresh else ['STALE_OR_INCOMPLETE'],valid_binding=valid))
        except (KeyError,TypeError,ValueError,AttributeError):
            # A malformed interface must not turn another address into "free".
            malformed = True
    if malformed:
        for network in result:
            network['fresh'] = False
            network['limitations'].append('INCOMPLETE_INTERFACE_SNAPSHOT')
    return result


def address_rows(network, extra_evidence=(), complete=True):
    return ranges(network['cidr'], [*network['evidence'], *extra_evidence], network['fresh'] and complete)


def search_networks(networks, text):
    address = ip_address(text)
    return [n for n in networks if address in ip_network(n['cidr'])]


def network_page(networks, selected='', search='', state=''):
    """Keep the chosen network through every filter, including empty searches."""
    from copy import deepcopy
    all_rows = deepcopy(networks)
    rows = [n for n in all_rows if n['id'] == selected] if selected else all_rows
    error = None
    alternatives = []
    if selected and not rows:
        error = 'Выбранная сеть недоступна или отсутствует в текущем снимке.'
    if search:
        try:
            address = ip_address(search)
            matches = search_networks(all_rows, search)
            if selected:
                if rows and address not in ip_network(rows[0]['cidr']):
                    alternatives = matches
                    error = ('Адрес относится к другой подсети.' if matches else
                             'Адрес не относится к известным сетям этого ресурса.')
                    for row in rows:
                        row['rows'] = []
                else:
                    for row in rows:
                        row['rows'] = [r for r in row['rows'] if ip_address(r['start']) <= address <= ip_address(r['end'])]
            else:
                rows = matches
                if not rows: error = 'Адрес не относится к известным сетям этого ресурса.'
                elif len(rows) > 1: error = 'Адрес найден в нескольких сетевых контекстах. Выберите сеть.'
                for row in rows:
                    row['rows'] = [r for r in row['rows'] if ip_address(r['start']) <= address <= ip_address(r['end'])]
        except ValueError:
            error = 'Введите корректный IP-адрес.'
            for row in rows: row['rows'] = []
    states = {'excluded': ('unusable','gateway','reserved','dhcp'),
              'occupied': ('assigned','observed','conflict')}
    if state:
        for row in rows:
            row['rows'] = [r for r in row['rows'] if r['state'] in states.get(state, (state,))]
    return rows, error, alternatives
