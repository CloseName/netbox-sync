"""Read-only inventory for the legacy VM planner, preserving its index policy."""

from dataclasses import dataclass
from .netbox_record_values import object_id as _object_id


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


def prepare_vm_network_plan_inventory(nb_api, cluster, *, _canonical_mac, _canonical_address):
    """Preserve read order and legacy address-only IP keys, including VLAN/prefix data."""
    target_vms = list(nb_api.virtualization.virtual_machines.filter(cluster_id=cluster.id))

    all_interfaces = list(nb_api.virtualization.interfaces.all())

    all_macs = list(nb_api.dcim.mac_addresses.all())

    all_ips = list(nb_api.ipam.ip_addresses.all())

    all_vlans = list(nb_api.ipam.vlans.all())

    all_prefixes = list(nb_api.ipam.prefixes.all())

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

    macs_by_address = {}

    for mac in all_macs:
        data = mac.serialize()

        value = _canonical_mac(data.get("mac_address"))

        if value:
            macs_by_address.setdefault(
                value,
                [],
            ).append(mac)

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

    return VMNetworkPlanInventory(
        target_vms=target_vms,
        interfaces_by_vm=interfaces_by_vm,
        macs_by_address=macs_by_address,
        ips_by_address=ips_by_address,
        ips_by_id=ips_by_id,
        vlans_by_vid=vlans_by_vid,
        prefixes_by_prefix=prefixes_by_prefix,
    )
