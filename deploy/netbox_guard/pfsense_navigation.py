"""Read-only pfSense menu tree. Paths are stable and independent of object UUIDs."""
from urllib.parse import urlencode


def leaf(key, label, component='', table='', **extra):
    return dict(key=key, label=label, component=component, table=table, **extra)


def branch(key, label, children):
    return dict(key=key, label=label, children=children)


MENU = [
    branch('system', 'System', [
        branch('general', 'General Setup', [leaf('settings', 'General', 'general', 'settings'), leaf('dns', 'DNS Servers', 'general', 'dns'), leaf('webgui', 'webConfigurator', 'general', 'webgui')]),
        branch('certificates', 'Certificates', [leaf('authorities', 'Authorities', 'certificates', 'authorities'), leaf('certificates', 'Certificates', 'certificates', 'certificates'), leaf('crls', 'Certificate Revocation Lists', 'certificates', 'crls')]),
        branch('users', 'User Manager', [leaf('users', 'Users', 'users', 'users'), leaf('groups', 'Groups', 'users', 'groups'), leaf('authservers', 'Authentication Servers', 'users', 'authservers'), leaf('settings', 'Settings', 'users', 'settings')]),
        branch('routing', 'Routing', [leaf('gateways', 'Gateways', 'routing', 'gateways'), leaf('groups', 'Gateway Groups', 'routing', 'groups'), leaf('static_routes', 'Static Routes', 'routing', 'static_routes'), leaf('defaults', 'Default Gateways', 'routing', 'defaults')]),
        leaf('advanced', 'Advanced'), leaf('packages', 'Package Manager', special='packages'),
    ]),
    branch('interfaces', 'Interfaces', [leaf('assignments', 'Assignments', 'interfaces', 'interfaces'), leaf('vlans', 'VLANs', 'interfaces', 'vlans')]),
    branch('firewall', 'Firewall', [
        leaf('rules', 'Rules', 'firewall', 'rules', group_by='interface'),
        branch('nat', 'NAT', [leaf('port_forwards', 'Port Forward', 'nat', 'port_forwards'), leaf('one_to_one', '1:1', 'nat', 'one_to_one'), leaf('outbound', 'Outbound', 'nat', 'outbound'), leaf('mode', 'Outbound Mode', 'nat', 'mode')]),
        leaf('aliases', 'Aliases', 'aliases', 'aliases'), leaf('schedules', 'Schedules', 'schedules', 'schedules'),
    ]),
    branch('services', 'Services', [
        branch('dhcp', 'DHCP Server', [leaf('ipv4', 'IPv4', 'dhcp', 'ipv4', group_by='interface'), leaf('ipv6', 'IPv6', 'dhcp', 'ipv6', group_by='interface'), leaf('static_ipv4', 'Static Mappings', 'dhcp', 'static_ipv4', group_by='interface')]),
        branch('dns_resolver', 'DNS Resolver', [leaf('settings', 'General Settings', 'dns_resolver', 'settings'), leaf('hosts', 'Host Overrides', 'dns_resolver', 'hosts'), leaf('domains', 'Domain Overrides', 'dns_resolver', 'domains')]),
        branch('dns_forwarder', 'DNS Forwarder', [leaf('settings', 'General Settings', 'dns_forwarder', 'settings'), leaf('hosts', 'Host Overrides', 'dns_forwarder', 'hosts')]),
        branch('haproxy', 'HAProxy', [leaf('settings', 'Settings', 'haproxy', 'settings'), leaf('frontends', 'Frontend', 'haproxy', 'frontends'), leaf('backends', 'Backend', 'haproxy', 'backends')]),
    ]),
    branch('vpn', 'VPN', [
        branch('ipsec', 'IPsec', [leaf('tunnels', 'Tunnels', 'ipsec', 'phase1'), leaf('settings', 'Settings', 'ipsec', 'settings')]),
        branch('openvpn', 'OpenVPN', [leaf('servers', 'Servers', 'openvpn', 'servers'), leaf('clients', 'Clients', 'openvpn', 'clients'), leaf('client_overrides', 'Client Specific Overrides', 'openvpn', 'client_overrides')]),
        leaf('wireguard', 'WireGuard', 'wireguard', 'tunnels'),
    ]),
    branch('status', 'Status', [leaf('system', 'System', special='coverage'), leaf('services', 'Services', special='services')]),
    branch('diagnostics', 'Diagnostics', [leaf('routes', 'Routes', special='routes'), leaf('nat', 'NAT Rules', special='nat')]),
    branch('help', 'Help', [leaf('about', 'About / Documentation', special='help')]),
]

LEGACY = {'overview': ('status', 'system'), 'interfaces': ('interfaces', 'assignments'),
          'rules': ('firewall', 'rules'), 'nat': ('firewall', 'nat'), 'aliases': ('firewall', 'aliases'),
          'routes': ('system', 'routing'), 'vpn': ('vpn', 'ipsec'), 'services': ('services', 'dhcp'),
          'observations': ('status', 'system')}


def resolve(params):
    """Unknown paths fall back to the first child, never to a cross-appliance query."""
    section_key, page_key = LEGACY.get(params.get('tab'), ('system', 'general'))
    section = next((s for s in MENU if s['key'] == params.get('section', section_key)), MENU[0])
    page = next((p for p in section['children'] if p['key'] == params.get('view', page_key)), section['children'][0])
    child = next((p for p in page.get('children', []) if p['key'] == params.get('sub')), None)
    selected = child or (page['children'][0] if page.get('children') else page)
    path = dict(section=section['key'], view=page['key'])
    if page.get('children'):
        path['sub'] = selected['key']
    return section, page, selected, path


def links(items, path, field):
    return [dict(item, active=path.get(field) == item['key'], url='?' + urlencode({**path, field: item['key']})) for item in items]


def object_path(component, table):
    # Children live below their parents in the catalogue, not in a flat mega-list.
    table = {('ipsec', 'phase2'): 'phase1', ('wireguard', 'peers'): 'tunnels',
             ('haproxy', 'servers'): 'backends', ('schedules', 'ranges'): 'schedules',
             ('certificates', 'revocations'): 'crls'}.get((component, table), table)
    for section in MENU:
        for page in section['children']:
            for item in page.get('children', [page]):
                if (item.get('component'), item.get('table')) == (component, table):
                    path = dict(section=section['key'], view=page['key'])
                    if page.get('children'):
                        path['sub'] = item['key']
                    return '?' + urlencode(path)
    return '?section=status&view=system'
