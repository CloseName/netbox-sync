"""Allowlisted inventory ambiguity evidence. No provider payloads or descriptions."""
from collections import defaultdict
from dataclasses import dataclass
from ipaddress import ip_interface
from ..network_scopes import scope_key


@dataclass(frozen=True)
class ConflictParticipant:
    name: str
    external_id: str
    provider_object_id: str | None
    host_id: str
    interface: str | None = None
    interface_id: str | None = None
    address: str | None = None
    vrf_id: int | None = None
    netbox_id: int | None = None


@dataclass(frozen=True)
class InventoryConflict:
    kind: str
    value: str
    participants: tuple[ConflictParticipant, ...]


def inventory_conflicts(hosts):
    """Preserve ambiguities; bridge/VLAN labels do not establish separate IP realms."""
    identities = defaultdict(list)
    addresses = defaultdict(list)
    for host in hosts:
        for kind, members in (('vm', host.virtual_machines), ('lxc', host.containers)):
            for vm in members:
                external_id = str(getattr(vm, 'external_id', None) or vm.vmid)
                base = dict(name=vm.original_name, external_id=external_id,
                            provider_object_id=getattr(vm, 'provider_object_id', None),
                            host_id=host.source_id)
                identities[(kind, external_id)].append(ConflictParticipant(**base))
                for nic in vm.interfaces:
                    seen = set()
                    for raw in nic.ip_addresses:
                        try:
                            address = ip_interface(raw)
                        except ValueError:
                            continue  # Same unusable-address policy as the executor.
                        if any((address.ip.is_loopback, address.ip.is_link_local,
                                address.ip.is_multicast, address.ip.is_unspecified)):
                            continue
                        if str(address) in seen:
                            continue  # Identical fact within this specific NIC only.
                        seen.add(str(address))
                        addresses[scope_key(str(address.ip),nic.ip_vrf_id)].append(ConflictParticipant(
                            **base, interface=nic.name, interface_id=nic.external_id,
                            address=str(address),vrf_id=nic.ip_vrf_id))
                    for previous in nic.ip_scope_conflicts:
                        value=scope_key(str(ip_interface(previous['address']).ip),nic.ip_vrf_id)
                        addresses[value].append(ConflictParticipant(**base,interface=nic.name,
                            interface_id=nic.external_id,address=previous['address'],
                            vrf_id=previous['vrf_id'],netbox_id=previous['netbox_id']))
    result = []
    for (_, value), members in sorted(identities.items()):
        if len(members) > 1:
            result.append(InventoryConflict('VM_IDENTITY', value, tuple(members)))
    for value, members in sorted(addresses.items()):
        if len(members) > 1:
            result.append(InventoryConflict('IP_ASSIGNMENT', value, tuple(members)))
    return tuple(result)
