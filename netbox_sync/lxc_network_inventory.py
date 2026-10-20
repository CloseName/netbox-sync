"""Read-only LXC inventory; retain global identity lookup before cluster checks."""

from dataclasses import dataclass

from .netbox_record_values import object_id as _object_id
from .network_scopes import scope_key, object_id as scope_object_id


@dataclass(frozen=True)
class LXCNetworkInventory:
    """Original records with ordered duplicates and VRF-scoped address keys."""

    all_vms: list
    interfaces_by_vm: dict
    macs_by_address: dict
    ips_by_address: dict


def prepare_lxc_network_inventory(nb_api, *, _canonical_mac, _canonical_ip):
    """Read every VM, preserving LXC's cross-cluster identity conflict checks."""
    all_vms = list(nb_api.virtualization.virtual_machines.all())

    all_interfaces = list(nb_api.virtualization.interfaces.all())

    all_macs = list(nb_api.dcim.mac_addresses.all())

    all_ips = list(nb_api.ipam.ip_addresses.all())

    interfaces_by_vm = {}

    for interface in all_interfaces:
        vm_id = _object_id(interface.serialize().get("virtual_machine"))

        if vm_id is not None:
            interfaces_by_vm.setdefault(
                vm_id,
                [],
            ).append(interface)

    macs_by_address = {}

    for mac in all_macs:
        value = _canonical_mac(mac.serialize().get("mac_address"))

        if value:
            macs_by_address.setdefault(
                value,
                [],
            ).append(mac)

    ips_by_address = {}

    for ip in all_ips:
        value = ip.serialize().get("address")

        if not value:
            continue

        try:
            canonical = _canonical_ip(value)
        except ValueError:
            continue

        ips_by_address.setdefault(
            scope_key(canonical, scope_object_id(ip.serialize().get("vrf"))),
            [],
        ).append(ip)

    return LXCNetworkInventory(
        all_vms=all_vms,
        interfaces_by_vm=interfaces_by_vm,
        macs_by_address=macs_by_address,
        ips_by_address=ips_by_address,
    )
