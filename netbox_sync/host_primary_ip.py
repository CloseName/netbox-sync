"""Map a source endpoint to a proven host interface, never infer NAT ownership."""
from ipaddress import ip_address, ip_interface
import socket
from .source_identity import SourceIdentity
from .netbox_metadata import find_sync_identity_matches


class HostPrimaryIPConflict(ValueError):
    code = "HOST_PRIMARY_IP_CONFLICT"


def select_endpoint(hosts, config, resolver=None):
    """Resolve once per discovery; plan/apply re-discovery fences DNS changes."""
    for host in hosts:
        host.connection_management = None
    try:
        addresses = {str(ip_address(config.address))}
    except ValueError:
        resolve = resolver or socket.getaddrinfo
        try:
            addresses = {str(ip_address(row[4][0])) for row in resolve(
                config.address, config.api_port, socket.AF_INET, socket.SOCK_STREAM)}
        except OSError:
            addresses = set()
    addresses = {address for address in addresses if ip_address(address).version == 4}
    # Multiple A records do not prove which endpoint served the request.
    if len(addresses) != 1:
        print('HOST PRIMARY IP: endpoint IPv4 is missing or ambiguous; retaining existing primary')
        return hosts
    endpoint = next(iter(addresses))
    matches = []
    for host in hosts:
        if host.source == 'esxi':
            rows = [(row.get('name'), str(row.get('ipv4'))+'/'+str(row.get('subnet_mask')))
                    for row in (host.esxi_host_network or {}).get('vmkernel', [])
                    if row.get('name') and row.get('ipv4') and row.get('subnet_mask')]
        else:
            rows = [(nic.name, address) for nic in host.interfaces for address in nic.addresses]
        for name, raw in rows:
            try:
                address = ip_interface(raw)
            except ValueError:
                continue
            if address.version == 4 and str(address.ip) == endpoint:
                matches.append((host, name, str(address)))
    if len(matches) != 1:
        print('HOST PRIMARY IP: endpoint does not match one host interface; retaining existing primary')
        return hosts
    host, name, address = matches[0]
    host.connection_management = dict(interface=name, address=address,
        dns_name='' if config.address == endpoint else config.address)
    if host.source == 'proxmox':
        host.management_ip = endpoint
    return hosts


def object_id(value):
    if isinstance(value, dict): return value.get('id')
    return value if isinstance(value, int) else getattr(value, 'id', None)


def apply_esxi_primary(api, hosts):
    """Create only the proven VMkernel interface/IP; preserve manual primaries."""
    for host in hosts:
        wanted = host.connection_management
        if not wanted: continue
        devices = find_sync_identity_matches(list(api.dcim.devices.all()), host)
        if len(devices) != 1: raise HostPrimaryIPConflict('Management IP requires one source-owned host')
        device = devices[0]
        identity = SourceIdentity('v2', 'esxi', host.source_instance, 'host-nic',
                                  host.source_id+':'+wanted['interface']).to_record()
        interfaces = [nic for nic in api.dcim.interfaces.all()
                      if object_id(nic.serialize().get('device')) == device.id
                      and nic.name == wanted['interface']]
        if len(interfaces) > 1: raise HostPrimaryIPConflict('Ambiguous management interface')
        nic = interfaces[0] if interfaces else None
        if nic and (getattr(nic, 'custom_fields', {}) or {}).get('sync_identities') != [identity]:
            raise HostPrimaryIPConflict('Management interface exists without matching source ownership')
        address = ip_interface(wanted['address'])
        matches = []
        for ip in api.ipam.ip_addresses.all():
            if ip_interface(ip.address).ip == address.ip: matches.append(ip)
        if len(matches) > 1: raise HostPrimaryIPConflict('Management IP is ambiguous across NetBox scopes')
        ip = matches[0] if matches else None
        if ip:
            data = ip.serialize()
            if (data.get('vrf') is not None or str(ip_interface(ip.address)) != str(address)
                    or nic is None or data.get('assigned_object_type') != 'dcim.interface'
                    or object_id(data.get('assigned_object_id')) != nic.id):
                raise HostPrimaryIPConflict('Management IP already exists with a different assignment or prefix')
        primary = object_id(device.serialize().get('primary_ip4'))
        if primary is not None and (ip is None or primary != ip.id):
            raise HostPrimaryIPConflict('Existing primary IPv4 requires operator review; not overwritten')
        if nic is None:
            nic = api.dcim.interfaces.create(device=device.id, name=wanted['interface'],
                type='virtual', enabled=True, mgmt_only=True,
                custom_fields={'sync_identities': [identity]})
        if ip is None:
            ip = api.ipam.ip_addresses.create(address=str(address), status='active',
                assigned_object_type='dcim.interface', assigned_object_id=nic.id,
                dns_name=wanted['dns_name'])
        if primary != ip.id:
            device.update({'primary_ip4': ip.id})
