"""Stable traversal of unordered discovered inventory, shared by plan and apply."""
from copy import deepcopy
from dataclasses import asdict
import json
from ipaddress import ip_interface


def canonical_hosts(hosts):
    def key(value):
        identity = next((getattr(value, name) for name in ('source_id', 'external_id', 'name', 'path')
                         if getattr(value, name, None) is not None), '')
        return str(identity), json.dumps(asdict(value), sort_keys=True, separators=(',', ':'))

    result = deepcopy(list(hosts))
    def normalize(value):
        # These are inventory memberships, not executable operation sequences.
        for field in ('interfaces', 'virtual_machines', 'containers', 'disks', 'storages'):
            if hasattr(value, field):
                members = getattr(value, field)
                for member in members: normalize(member)
                members.sort(key=key)
        for field in ('addresses', 'ip_addresses', 'bridge_ports'):
            if hasattr(value, field):
                members = getattr(value, field)
                if field == 'ip_addresses':
                    normalized = []
                    for address in members:
                        try: normalized.append(str(ip_interface(address)))
                        except ValueError: normalized.append(address)
                    members[:] = sorted(set(normalized))
                else:
                    members.sort()
    for host in result: normalize(host)
    return sorted(result, key=key)
