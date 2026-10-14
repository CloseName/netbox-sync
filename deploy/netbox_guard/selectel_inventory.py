"""Server-only, allowlisted projection of a read-only Selectel audit.

Provider assignments are observations, never proof of the host's actual IP,
NAT, cabling or installed OS. All joins use provider IDs within account/scope.
No Django dependency: normalization and failure retention can be tested offline.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json

from .provider_policy import identity

HARDWARE = ('count', 'name', 'type', 'size', 'base_freq', 'cores_per_cpu',
            'threads_per_cpu', 'unit', 'power_supply', 'vendor', 'model', 'serial')
IP = ('uuid', 'resource_uuid', 'ip', 'version', 'subnet_uuid', 'subnet_type',
      'network_uuid', 'network', 'subnet', 'netmask', 'gateway', 'broadcast', 'project_uuid')
SUBNET = ('uuid', 'resource_uuid', 'location_uuid', 'network_uuid', 'subnet',
          'network', 'version', 'prefixlen', 'gateway', 'netmask', 'nexthop', 'vrrp')
NETWORK = ('uuid', 'location_uuid', 'vlan', 'network_type', 'is_shared', 'project_uuid',
           'dhcp_flag', 'l2_vpn_flag', 'l3_vpn_flag')
PORT = ('uuid', 'port_type', 'port_mode', 'speed', 'is_enabled', 'port_name',
        'hw_uuid', 'is_aggregate', 'aggregate_physical_port_count')
OS = ('arch', 'os_template', 'version', 'template_version', 'raid_type', 'is_processing',
      *[p + s for p in ('', 'local_') for s in ('ipv4_address', 'ipv4_gateway', 'ipv4_netmask',
                                             'ipv6_address', 'ipv6_gateway', 'ipv6_netmask')])
IMAGE = ('id', 'name', 'os_distro', 'os_type', 'architecture', 'min_ram', 'min_disk',
         'size', 'virtual_size', 'disk_format', 'container_format', 'status')


def pick(obj, fields):
    """Scalars only; complex structures require their own allowlist."""
    if not isinstance(obj, dict):
        return {}
    return {k: obj[k] for k in fields if k in obj and
            (obj[k] is None or type(obj[k]) in (str, int, float, bool))}


def rows(value):
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('SELECTEL_TIMESTAMP_INVALID') from None


class Inventory:
    def __init__(self, document):
        if (not isinstance(document, dict) or document.get('schema') != 'selectel-audit-v1'
                or document.get('account_verified') is not True
                or not isinstance(document.get('account'), str)
                or not isinstance(document.get('datasets'), list)):
            raise ValueError('SELECTEL_AUDIT_INVALID')
        self.account = document['account']
        self.observed = timestamp(document.get('finished_at')).isoformat()
        self.datasets = rows(document['datasets'])

    def get(self, service, kind, project='', region='', resource=None):
        found = [d for d in self.datasets if d.get('service') in service.split('|')
                 and d.get('kind') == kind and d.get('project', '') == project
                 and d.get('region', '') == region
                 and (resource is None or d.get('resource_id') == resource)]
        # Never choose arbitrarily between duplicate catalog observations.
        if len(found) > 1:
            canonical = {json.dumps(d.get('items'), sort_keys=True) for d in found}
            if len(canonical) != 1 or len({d.get('status') for d in found}) != 1:
                return {'status': 'CONFLICTING_DATASETS', 'items': []}
        return found[0] if found else {'status': 'NOT_COLLECTED', 'items': []}

    def section(self, dataset, data):
        code = dataset.get('status', 'NOT_COLLECTED')
        status = ('collected' if data else 'empty' if isinstance(data, list) else 'not_reported') if code == 'collected' else (
            'access_denied' if code in ('HTTP_401', 'HTTP_403') else
            'unavailable' if code == 'HTTP_404' else
            'not_collected' if code == 'NOT_COLLECTED' else 'partial' if dataset.get('items') else 'error')
        return {'status': status, 'code': code, 'observed_at': self.observed,
                'data': data, 'retained': False}

    def dedicated(self, obj, root):
        ident = obj.get('uuid')
        spec = dict(account=self.account, kind='dedicated', native_id=ident,
                    project=obj.get('project_uuid') or '', region='')
        key = identity(spec, 'device')
        sections = {}
        def ds(kind, detail=False):
            return self.get('dedicated', kind, resource=ident if detail else None)
        detail = ds('resource_detail', True)
        info = ds('resource_info', True)
        detail_obj = next(iter(rows(detail.get('items'))), {})
        info_obj = next(iter(rows(info.get('items'))), {})
        merged = {**obj, **detail_obj}
        sections['resource'] = self.section(root, pick(obj, ('uuid', 'user_desc', 'service_type',
            'state', 'project_uuid', 'hw_uuid', 'location_uuid', 'serial', 'service_tag', 'system_uuid')))
        sections['details'] = self.section(detail, pick(detail_obj, ('config_name', 'state', 'serial', 'service_tag', 'system_uuid')))
        config = info_obj.get('config') or {}
        hardware = {kind: [pick(v, HARDWARE) for v in rows(config.get(kind))]
                    for kind in ('cpu', 'ram', 'disk', 'board', 'case', 'gpu', 'pcie', 'misc', 'ocp')
                    if isinstance(config, dict) and kind in config}
        hardware.update(pick(info_obj, ('config_name', 'serial', 'service_tag', 'system_uuid')))
        sections['hardware'] = self.section(info, hardware)
        locations = ds('locations')
        location = next((v for v in rows(locations.get('items')) if v.get('uuid') == merged.get('location_uuid')), {})
        sections['placement'] = self.section(locations, pick(location, ('uuid', 'name', 'location_id')))
        operating = ds('operating_system', True)
        os_obj = next(iter(rows(operating.get('items'))), {})
        os_data = pick(os_obj, OS)
        if isinstance(os_obj.get('partitions'), list):
            os_data['partitions'] = [pick(v, ('expand', 'fstype', 'mount', 'size')) for v in rows(os_obj['partitions'])]
        # Partition keys identify volumes; values still have a strict schema.
        if isinstance(os_obj.get('partitions_config'), dict):
            os_data['partitions_config'] = {str(k): pick(v, ('type', 'device', 'fstype', 'mount', 'size', 'level'))
                                           for k, v in os_obj['partitions_config'].items()}
        sections['operating_system'] = self.section(operating, os_data)
        network_ids, subnet_ids = set(), set()
        for kind in ('public_ips', 'private_ips'):
            source = ds(kind)
            selected = [v for v in rows(source.get('items')) if v.get('resource_uuid') == ident]
            sections[kind] = self.section(source, [pick(v, IP) for v in selected])
            network_ids.update(v.get('network_uuid') for v in selected if v.get('network_uuid'))
            subnet_ids.update(v.get('subnet_uuid') for v in selected if v.get('subnet_uuid'))
        ports = ds('ports')
        selected_ports = [v for v in rows(ports.get('items')) if merged.get('hw_uuid')
                          and v.get('hw_uuid') == merged['hw_uuid']]
        port_data = []
        for port in selected_ports:
            value = pick(port, PORT)
            value['networks'] = [pick(n, NETWORK) for n in rows(port.get('network'))]
            value['aux_network_info'] = pick(port.get('aux_network_info'), (
                'availability_zone', 'peer_name', 'asn', 'peer_asn', 'peer_ip', 'client_ip', 'subnet', 'mac_address'))
            network_ids.update(n.get('uuid') for n in value['networks'] if n.get('uuid'))
            port_data.append(value)
        sections['ports'] = self.section(ports, port_data)
        for kind in ('public_subnets', 'private_subnets'):
            source = ds(kind)
            selected = [v for v in rows(source.get('items')) if v.get('resource_uuid') == ident
                        or v.get('uuid') in subnet_ids]
            sections[kind] = self.section(source, [pick(v, SUBNET) for v in selected])
            network_ids.update(v.get('network_uuid') for v in selected if v.get('network_uuid'))
        networks = ds('networks')
        sections['networks'] = self.section(networks, [pick(v, NETWORK) for v in rows(networks.get('items'))
                                                       if v.get('uuid') in network_ids])
        if not merged.get('hw_uuid'):
            sections['ports'].update(status='not_reported', code='HARDWARE_ID_NOT_REPORTED')
        for kind, dependency in (('public_subnets', 'public_ips'), ('private_subnets', 'private_ips')):
            if ds(dependency).get('status') != 'collected':
                sections[kind].update(status='partial', code='IP_DEPENDENCY_INCOMPLETE')
        if any(ds(k).get('status') != 'collected' for k in ('ports', 'public_ips', 'private_ips', 'public_subnets', 'private_subnets')):
            sections['networks'].update(status='partial', code='NETWORK_DEPENDENCY_INCOMPLETE')
        return key, {'schema': 1, 'identity': spec, 'sections': sections}

    def cloud(self, obj, root):
        project, region = root.get('project', ''), root.get('region', '')
        spec = dict(account=self.account, kind='cloud_vm', native_id=obj.get('id'), project=project, region=region)
        key = identity(spec, 'vm')
        sections = {}
        def ds(service, kind):
            return self.get(service, kind, project, region)
        sections['resource'] = self.section(root, pick(obj, ('id', 'name', 'status', 'created', 'updated',
            'OS-EXT-STS:vm_state', 'OS-EXT-STS:power_state', 'OS-EXT-STS:task_state')))
        sections['placement'] = self.section(root, pick(obj, ('OS-EXT-AZ:availability_zone',)))
        flavor = ds('compute', 'flavors')
        flavor_id = obj.get('flavor', {}).get('id') if isinstance(obj.get('flavor'), dict) else None
        sections['hardware'] = self.section(flavor, next((pick(v, ('id', 'name', 'vcpus', 'ram', 'disk',
            'swap', 'OS-FLV-EXT-DATA:ephemeral')) for v in rows(flavor.get('items')) if v.get('id') == flavor_id), {}))
        images = ds('image', 'images')
        image_id = obj.get('image', {}).get('id') if isinstance(obj.get('image'), dict) else None
        sections['operating_system'] = self.section(images, next((pick(v, IMAGE) for v in rows(images.get('items'))
                                                                  if v.get('id') == image_id), {}))
        # Nova addresses are provider-reported; no inference that they are host management addresses.
        addresses = obj.get('addresses') or {}
        sections['addresses'] = self.section(root, {k: [pick(v, ('version', 'addr', 'OS-EXT-IPS:type', 'OS-EXT-IPS-MAC:mac_addr'))
            for v in rows(values)] for k, values in addresses.items()} if isinstance(addresses, dict) else {})
        ports = ds('network', 'ports')
        selected = [v for v in rows(ports.get('items')) if v.get('device_id') == spec['native_id']]
        port_ids = {v.get('id') for v in selected}
        net_ids = {v.get('network_id') for v in selected}
        subnet_ids, group_ids = set(), set()
        port_data = []
        for v in selected:
            p = pick(v, ('id', 'name', 'network_id', 'mac_address', 'device_id', 'device_owner', 'status',
                         'admin_state_up', 'port_security_enabled', 'mtu', 'binding:vnic_type'))
            p['fixed_ips'] = [pick(x, ('subnet_id', 'ip_address')) for x in rows(v.get('fixed_ips'))]
            p['allowed_address_pairs'] = [pick(x, ('ip_address', 'mac_address')) for x in rows(v.get('allowed_address_pairs'))]
            p['security_groups'] = [x for x in v.get('security_groups', []) if isinstance(x, str)]
            subnet_ids.update(x.get('subnet_id') for x in p['fixed_ips'])
            group_ids.update(p['security_groups'])
            port_data.append(p)
        sections['ports'] = self.section(ports, port_data)
        for kind, ids, fields in (
            ('networks', net_ids, ('id', 'name', 'mtu', 'status', 'shared', 'router:external', 'provider:network_type',
                                  'provider:segmentation_id', 'provider:physical_network')),
            ('subnets', subnet_ids, ('id', 'name', 'network_id', 'cidr', 'ip_version', 'gateway_ip', 'enable_dhcp'))):
            source = ds('network', kind)
            data = []
            for v in rows(source.get('items')):
                if v.get('id') not in ids:
                    continue
                entry = pick(v, fields)
                if kind == 'subnets':
                    entry['allocation_pools'] = [pick(x, ('start', 'end')) for x in rows(v.get('allocation_pools'))]
                    entry['host_routes'] = [pick(x, ('destination', 'nexthop')) for x in rows(v.get('host_routes'))]
                    entry['dns_nameservers'] = [x for x in v.get('dns_nameservers', []) if isinstance(x, str)]
                data.append(entry)
            sections[kind] = self.section(source, data)
        floating = ds('network', 'floatingips')
        fips = [v for v in rows(floating.get('items')) if v.get('port_id') in port_ids]
        sections['floatingips'] = self.section(floating, [pick(v, ('id', 'floating_ip_address', 'fixed_ip_address',
            'port_id', 'router_id', 'floating_network_id', 'status')) for v in fips])
        router_ids = {v.get('router_id') for v in fips if v.get('router_id')}
        router_ids.update(v.get('device_id') for v in rows(ports.get('items'))
                          if v.get('network_id') in net_ids and str(v.get('device_owner', '')).startswith('network:router'))
        routers = ds('network', 'routers')
        router_data = []
        for v in rows(routers.get('items')):
            if v.get('id') not in router_ids:
                continue
            r = pick(v, ('id', 'name', 'status', 'admin_state_up', 'distributed', 'ha'))
            r['routes'] = [pick(x, ('destination', 'nexthop')) for x in rows(v.get('routes'))]
            gateway = v.get('external_gateway_info') or {}
            r['external_gateway_info'] = {**pick(gateway, ('network_id', 'enable_snat')),
                'external_fixed_ips': [pick(x, ('subnet_id', 'ip_address')) for x in rows(gateway.get('external_fixed_ips'))]}
            router_data.append(r)
        sections['routers'] = self.section(routers, router_data)
        groups = ds('network', 'security-groups')
        sections['security_groups'] = self.section(groups, [{**pick(v, ('id', 'name')),
            'rules': [pick(x, ('id', 'direction', 'ethertype', 'protocol', 'port_range_min', 'port_range_max',
                              'remote_ip_prefix', 'remote_group_id')) for x in rows(v.get('security_group_rules'))]}
            for v in rows(groups.get('items')) if v.get('id') in group_ids])
        volumes = ds('volumev3|volumev2', 'volumes')
        attached = {v.get('id') for v in rows(obj.get('os-extended-volumes:volumes_attached'))}
        disks = []
        for v in rows(volumes.get('items')):
            attachments = [a for a in rows(v.get('attachments')) if a.get('server_id') == spec['native_id']]
            if v.get('id') not in attached and not attachments:
                continue
            disk = pick(v, ('id', 'name', 'status', 'size', 'availability_zone', 'volume_type', 'bootable', 'encrypted', 'multiattach'))
            disk['attachments'] = [pick(a, ('server_id', 'device', 'attachment_id', 'attached_at')) for a in attachments]
            disk['image'] = pick(v.get('volume_image_metadata'), ('image_id', 'image_name', 'os_type', 'os_distro', 'x_sel_image_os_dist'))
            disks.append(disk)
        sections['volumes'] = self.section(volumes, disks)
        snapshots = ds('volumev3|volumev2', 'snapshots')
        disk_ids = {v['id'] for v in disks}
        sections['volume_snapshots'] = self.section(snapshots, [pick(v, ('id', 'volume_id', 'name', 'size', 'status', 'created_at'))
            for v in rows(snapshots.get('items')) if v.get('volume_id') in disk_ids])
        # A failed ports listing must not turn dependent network joins into authoritative emptiness.
        if ports.get('status') != 'collected':
            for name in ('networks', 'subnets', 'floatingips', 'routers', 'security_groups'):
                sections[name].update(status='partial', code='PORTS_DEPENDENCY_INCOMPLETE')
        if volumes.get('status') != 'collected':
            sections['volume_snapshots'].update(status='partial', code='VOLUMES_DEPENDENCY_INCOMPLETE')
        return key, {'schema': 1, 'identity': spec, 'sections': sections}

    def normalize(self):
        result = {}
        for dataset in self.datasets:
            dedicated = dataset.get('service') == 'dedicated' and dataset.get('kind') == 'resources'
            cloud = dataset.get('service') == 'compute' and dataset.get('kind') == 'servers'
            if not (dedicated or cloud):
                continue
            for obj in rows(dataset.get('items')):
                if dedicated and obj.get('service_type') not in ('server', 'serverchip', 'custom', 'colocation'):
                    continue
                key, record = self.dedicated(obj, dataset) if dedicated else self.cloud(obj, dataset)
                if key in result and result[key] != record:
                    raise ValueError('SELECTEL_RESOURCE_CONFLICT')
                result[key] = record
        return result


def merge_snapshot(previous, incoming):
    result = deepcopy(incoming)
    for name, current in result['sections'].items():
        old = (previous or {}).get('sections', {}).get(name)
        # Both a 403 and a missing field are unknown, not permission to erase data.
        if current['status'] not in ('collected', 'empty') and old and old.get('data'):
            current['data'] = deepcopy(old['data'])
            current['data_observed_at'] = old.get('data_observed_at', old['observed_at'])
            current['retained'] = True
        else:
            current['data_observed_at'] = current['observed_at']
    return result


def projection(snapshot):
    sections = snapshot['sections']
    data = lambda name: sections.get(name, {}).get('data') or {}
    placement = data('placement')
    hardware = data('hardware')
    os_data = data('operating_system')
    location = placement.get('name') or placement.get('OS-EXT-AZ:availability_zone') or ''
    config = hardware.get('config_name') or data('details').get('config_name') or ''
    if not config and 'vcpus' in hardware:
        config = f"{hardware['vcpus']} vCPU / {hardware.get('ram', '?')} MiB RAM / {hardware.get('disk', '?')} GiB local disk"
    operating = ' '.join(str(os_data.get(k) or '') for k in ('os_template', 'version', 'name', 'os_distro')).strip()
    addresses = [x.get('ip') for k in ('public_ips', 'private_ips') for x in data(k) if isinstance(x, dict)]
    addresses += [x.get('floating_ip_address') for x in data('floatingips') if isinstance(x, dict)]
    if isinstance(data('addresses'), dict):
        addresses += [x.get('addr') for values in data('addresses').values() for x in rows(values)]
    health = '; '.join(f"{k}: {v['status']}" + (' (last known retained)' if v.get('retained') else '')
                       for k, v in sections.items() if v['status'] != 'collected') or 'Collected'
    return {'selectel_inventory': snapshot, 'selectel_location': location or 'Not reported',
            'selectel_configuration': config or 'Not reported', 'selectel_os': operating or 'Not reported',
            'selectel_networks': ', '.join(sorted({str(x) for x in addresses if x})) or 'Not reported',
            'selectel_collection_status': health}
