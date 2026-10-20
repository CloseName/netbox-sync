"""Read and index VM network inventory without changing NetBox records."""

from dataclasses import dataclass
import ipaddress

from .netbox_record_values import object_id as _object_id
from .network_inventory_index import index_mac_records
from .network_scopes import scope_key, object_id as scope_object_id


@dataclass(frozen=True)
class VMNetworkInventory:
    """Original records and ordered duplicate-preserving lookup collections."""

    target_vms: list
    interfaces_by_vm: dict
    interfaces_by_id: dict
    macs_by_address: dict
    ips_by_address: dict
    ips_by_id: dict


def _index_interfaces(all_interfaces):
    """Index original interfaces by record ID and parent VM without collapsing duplicates."""
    interfaces_by_vm = {}
    interfaces_by_id = {}

    for interface in all_interfaces:
        interfaces_by_id[interface.id] = interface
        vm_id = _object_id(interface.serialize().get("virtual_machine"))

        if vm_id is not None:
            interfaces_by_vm.setdefault(
                vm_id,
                [],
            ).append(interface)

    return interfaces_by_vm, interfaces_by_id


def _index_ips(all_ips):
    """Index original IPs by ID and canonical address plus VRF, retaining scoped duplicates."""
    ips_by_address = {}
    ips_by_id = {}

    for ip in all_ips:
        ips_by_id[ip.id] = ip
        address = ip.serialize().get("address")

        if not address:
            continue

        try:
            canonical = str(ipaddress.ip_interface(address))
        except ValueError:
            continue

        ips_by_address.setdefault(
            scope_key(canonical, scope_object_id(ip.serialize().get("vrf"))),
            [],
        ).append(ip)

    return ips_by_address, ips_by_id


def prepare_vm_network_inventory(nb_api, cluster, *, _canonical_mac):
    """Preserve read order and propagate failures before any mutation can begin."""
    target_vms = list(nb_api.virtualization.virtual_machines.filter(cluster_id=cluster.id))

    all_interfaces = list(nb_api.virtualization.interfaces.all())

    all_macs = list(nb_api.dcim.mac_addresses.all())

    all_ips = list(nb_api.ipam.ip_addresses.all())

    interfaces_by_vm, interfaces_by_id = _index_interfaces(all_interfaces)
    macs_by_address = index_mac_records(all_macs, _canonical_mac)
    ips_by_address, ips_by_id = _index_ips(all_ips)

    return VMNetworkInventory(
        target_vms=target_vms,
        interfaces_by_vm=interfaces_by_vm,
        interfaces_by_id=interfaces_by_id,
        macs_by_address=macs_by_address,
        ips_by_address=ips_by_address,
        ips_by_id=ips_by_id,
    )
