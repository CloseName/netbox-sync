"""Read-only inventory for the legacy VM planner, preserving its index policy."""

from dataclasses import dataclass
from .netbox_record_values import object_id as _object_id
from .network_inventory_index import index_mac_records


@dataclass(frozen=True)
class VMNetworkPlanInventory:
    """Original records and duplicate-preserving planner indexes."""

    target_vms: list
    interfaces_by_vm: dict
    macs_by_address: dict
    ips_by_address: dict
    ips_by_id: dict
    vlans_by_vid: dict
    prefixes_by_prefix: dict


def _index_interfaces(all_interfaces):
    """Group legacy planner interfaces by parent VM, ignoring unbound records."""
    interfaces_by_vm = {}

    for interface in all_interfaces:
        data = interface.serialize()

        vm_id = _object_id(data.get("virtual_machine"))

        if vm_id is None:
            continue

        interfaces_by_vm.setdefault(
            vm_id,
            [],
        ).append(interface)

    return interfaces_by_vm


def _index_ips(all_ips, _canonical_address):
    """Index legacy planner IPs by ID and address only, preserving its VRF-independent policy."""
    ips_by_address = {}
    ips_by_id = {}

    for ip in all_ips:
        data = ip.serialize()

        ips_by_id[ip.id] = ip

        address = data.get("address")

        if not address:
            continue

        try:
            canonical = _canonical_address(address)
        except ValueError:
            continue

        ips_by_address.setdefault(
            canonical,
            [],
        ).append(ip)

    return ips_by_address, ips_by_id


def _index_vlans(all_vlans):
    """Group VLAN records by integer VID and propagate invalid conversions."""
    vlans_by_vid = {}

    for vlan in all_vlans:
        data = vlan.serialize()

        vid = data.get("vid")

        if vid is None:
            continue

        vlans_by_vid.setdefault(
            int(vid),
            [],
        ).append(vlan)

    return vlans_by_vid


def _index_prefixes(all_prefixes):
    """Group original prefixes by nonempty string values without network normalization."""
    prefixes_by_prefix = {}

    for prefix in all_prefixes:
        data = prefix.serialize()

        value = data.get("prefix")

        if not value:
            continue

        prefixes_by_prefix.setdefault(
            str(value),
            [],
        ).append(prefix)

    return prefixes_by_prefix


def prepare_vm_network_plan_inventory(nb_api, cluster, *, _canonical_mac, _canonical_address):
    """Preserve read order and legacy address-only IP keys, including VLAN/prefix data."""
    target_vms = list(nb_api.virtualization.virtual_machines.filter(cluster_id=cluster.id))

    all_interfaces = list(nb_api.virtualization.interfaces.all())

    all_macs = list(nb_api.dcim.mac_addresses.all())

    all_ips = list(nb_api.ipam.ip_addresses.all())

    all_vlans = list(nb_api.ipam.vlans.all())

    all_prefixes = list(nb_api.ipam.prefixes.all())

    interfaces_by_vm = _index_interfaces(all_interfaces)
    macs_by_address = index_mac_records(all_macs, _canonical_mac)
    ips_by_address, ips_by_id = _index_ips(all_ips, _canonical_address)
    vlans_by_vid = _index_vlans(all_vlans)
    prefixes_by_prefix = _index_prefixes(all_prefixes)

    return VMNetworkPlanInventory(
        target_vms=target_vms,
        interfaces_by_vm=interfaces_by_vm,
        macs_by_address=macs_by_address,
        ips_by_address=ips_by_address,
        ips_by_id=ips_by_id,
        vlans_by_vid=vlans_by_vid,
        prefixes_by_prefix=prefixes_by_prefix,
    )
