"""Allowlisted ESXi host network observations; never creates network objects."""
import json


def value(obj, path, default=None):
    for part in path.split('.'):
        obj = getattr(obj, part, None)
        if obj is None:
            return default
    return obj


def text(obj, path):
    result = value(obj, path)
    return None if result is None else str(result)


def ordered(rows):
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=True))


def collect_host_network(host):
    network = value(host, 'config.network')
    if network is None:
        return {'version': 1, 'available': False}
    pnics = list(value(network, 'pnic', ()) or ())
    switches = list(value(network, 'vswitch', ()) or ())
    pnic_names = {str(value(p, 'key')): text(p, 'device') for p in pnics if value(p, 'key')}
    def uplinks(switch):
        return sorted(str(pnic_names.get(str(key)) or key)
                      for key in (value(switch, 'pnic', ()) or ()))
    physical = []
    for pnic in pnics:
        name = text(pnic, 'device')
        physical.append({
            'name': name, 'mac': text(pnic, 'mac'), 'driver': text(pnic, 'driver'),
            'link_up': value(pnic, 'linkSpeed') is not None,
            'speed_mbps': value(pnic, 'linkSpeed.speedMb'),
            'full_duplex': value(pnic, 'linkSpeed.duplex'),
            'switches': sorted(text(s, 'name') for s in switches
                               if name in uplinks(s) and text(s, 'name')),
        })
    groups = [{
        'name': text(group, 'spec.name'), 'switch': text(group, 'spec.vswitchName'),
        'vlan_id': value(group, 'spec.vlanId'),
    } for group in (value(network, 'portgroup', ()) or ())]
    virtual_switches = [{
        'name': text(s, 'name'), 'mtu': value(s, 'mtu'), 'uplinks': uplinks(s),
        'port_groups': sorted(g['name'] for g in groups
                              if g['switch'] == text(s, 'name') and g['name']),
    } for s in switches]
    kernel = []
    for nic in (value(network, 'vnic', ()) or ()):
        distributed = value(nic, 'spec.distributedVirtualPort')
        kernel.append({
            'name': text(nic, 'device'), 'mac': text(nic, 'spec.mac'),
            'port_group': text(nic, 'portgroup') or text(nic, 'spec.portgroup'),
            'mtu': value(nic, 'spec.mtu'), 'ipv4': text(nic, 'spec.ip.ipAddress'),
            'subnet_mask': text(nic, 'spec.ip.subnetMask'),
            'dhcp': value(nic, 'spec.ip.dhcp'),
            'ipv6': sorted(f"{text(ip, 'ipAddress')}/{value(ip, 'prefixLength')}"
                           for ip in (value(nic, 'spec.ip.ipV6Config.ipV6Address', ()) or ())
                           if text(ip, 'ipAddress') and value(ip, 'prefixLength') is not None),
            'distributed_switch_uuid': text(distributed, 'switchUuid'),
            'distributed_port_group_key': text(distributed, 'portgroupKey'),
            'distributed_port_key': text(distributed, 'portKey'),
        })
    # A standalone host exposes only part of distributed/opaque topology.
    # Report its presence explicitly, never infer a standard-switch connection.
    return {
        'version': 1, 'available': True, 'physical_nics': ordered(physical),
        'switches': ordered(virtual_switches), 'port_groups': ordered(groups),
        'vmkernel': ordered(kernel),
        'distributed_switch_count': len(value(network, 'proxySwitch', ()) or ()),
        'opaque_switch_count': len(value(network, 'opaqueSwitch', ()) or ()),
    }


class HostNetworkPrerequisiteError(ValueError):
    pass


def require_host_network_field(api):
    from .prerequisites import reconcile
    rows = [r.serialize() for r in api.extras.custom_fields.filter(name='esxi_host_network')]
    field = next(r for r in reconcile(rows) if r['name'] == 'esxi_host_network')
    if field['status'] != 'ready':
        raise HostNetworkPrerequisiteError('Prepare esxi_host_network in NetBox before synchronization')


def apply_host_network_snapshots(api, hosts):
    """Also cover managed legacy hosts without changing their placement/hardware."""
    from copy import deepcopy
    from .netbox_metadata import find_sync_identity_matches
    devices = list(api.dcim.devices.all())
    for host in hosts:
        if host.esxi_host_network is None:
            continue
        matches = find_sync_identity_matches(devices, host)
        if len(matches) != 1:
            raise ValueError('Expected one owned ESXi host for network snapshot')
        device = matches[0]
        fields = dict(getattr(device, 'custom_fields', None) or {})
        if fields.get('esxi_host_network') != host.esxi_host_network:
            fields['esxi_host_network'] = deepcopy(host.esxi_host_network)
            device.update({'custom_fields': fields})
