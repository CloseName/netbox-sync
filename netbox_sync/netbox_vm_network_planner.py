"""Orchestrate read-only VM interface, MAC, IP, VLAN and primary-IP planning."""

from .vm_network_plan_report import print_vm_network_plan_summary
from .vm_network_plan_interfaces import validate_plan_interfaces, match_plan_interface
from .vm_network_plan_vlan import plan_interface_vlan
from .vm_network_plan_primary import plan_primary_ipv4
from .vm_network_plan_ip import plan_interface_ips
from .vm_network_plan_mac import plan_interface_mac
from .vm_network_plan_inventory import prepare_vm_network_plan_inventory
from .netbox_record_values import object_id as _object_id
from .interface_display import validate_interface_names
from .netbox_vm_network_apply import _interface_match
from .netbox_vm_interface_metadata import find_nic_sync_identity_matches
import ipaddress

from .netbox_vm_metadata import find_vm_sync_identity_matches


def _canonical_mac(value):
    """Normalize a present MAC string to uppercase without adding format validation."""

    if not value:
        return None

    return str(value).strip().upper()


def _canonical_address(value):
    """Normalize an interface address while preserving its prefix length."""

    return str(ipaddress.ip_interface(str(value)))


def _usable_address(value):
    """Normalize candidate addresses, excluding loopback, link-local, multicast and unspecified IPs."""

    try:
        interface = ipaddress.ip_interface(str(value))
    except ValueError:
        return None

    address = interface.ip

    if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
        return None

    return str(interface)


def _network_of(address):
    """Derive the canonical network prefix from an interface address."""

    return str(ipaddress.ip_interface(address).network)


def _assigned_object(record):
    """Read an IP or MAC record assignment type and identifier."""

    data = record.serialize()

    return (
        data.get("assigned_object_type"),
        data.get("assigned_object_id"),
    )


def _scope_rank(data, site_id):
    """Prefer the selected site over unscoped records and exclude other scopes."""

    scope_type = data.get("scope_type")

    scope_id = data.get("scope_id")

    if scope_type == "dcim.site" and scope_id == site_id:
        return 0

    if scope_type is None and scope_id is None:
        return 1

    return None


def _select_scoped(
    records,
    site_id,
):
    """Choose one best-ranked scoped record or report absence or ambiguity."""

    eligible = []

    for record in records:
        data = record.serialize()

        rank = _scope_rank(
            data,
            site_id,
        )

        if rank is not None:
            eligible.append(
                (
                    rank,
                    record,
                )
            )

    if not eligible:
        return None, "not-found"

    best_rank = min(item[0] for item in eligible)

    best = [record for rank, record in eligible if rank == best_rank]

    if len(best) > 1:
        return None, "ambiguous"

    return best[0], "match"


def _vm_identity_match(
    target_vms,
    discovered_vm,
):
    """Find VM records by the existing ranked source-identity rules."""

    return find_vm_sync_identity_matches(target_vms, discovered_vm)


def _existing_primary_ipv4(
    vm,
    ips_by_id,
):
    """Resolve and canonicalize the current primary IPv4 when present in loaded inventory."""

    data = vm.serialize()

    primary_id = _object_id(data.get("primary_ip4"))

    if primary_id is None:
        return None

    ip = ips_by_id.get(primary_id)

    if ip is None:
        return None

    address = ip.serialize().get("address")

    if not address:
        return None

    return _canonical_address(address)


def plan_vm_networks(
    nb_api,
    host,
    cluster,
    site,
):
    """Plan interfaces, VLANs, MACs, IPs and primary IPv4 for uniquely matched VMs."""

    print()
    print("  QEMU VM NETWORK")

    if cluster is None:
        print("    BLOCKED target cluster does not exist")
        return

    inventory = prepare_vm_network_plan_inventory(
        nb_api,
        cluster,
        _canonical_mac=_canonical_mac,
        _canonical_address=_canonical_address,
    )
    counters = {
        "vm_match": 0,
        "vm_blocked": 0,
        "interface_create": 0,
        "interface_match": 0,
        "interface_conflict": 0,
        "mac_create": 0,
        "mac_match": 0,
        "mac_conflict": 0,
        "ip_create": 0,
        "ip_match": 0,
        "ip_conflict": 0,
        "primary_set": 0,
        "warnings": 0,
    }

    for discovered_vm in sorted(
        host.virtual_machines,
        key=lambda item: item.vmid,
    ):
        vm_matches = _vm_identity_match(
            inventory.target_vms,
            discovered_vm,
        )

        if len(vm_matches) != 1:
            counters["vm_blocked"] += 1

            print(
                f"    BLOCKED NETWORK "
                f"vmid={discovered_vm.vmid} "
                f"name={discovered_vm.original_name!r} "
                f"vm_matches={len(vm_matches)}"
            )

            continue

        netbox_vm = vm_matches[0]

        counters["vm_match"] += 1

        print()
        print(f"    VM id={netbox_vm.id} " f"vmid={discovered_vm.vmid} " f"name={discovered_vm.original_name!r}")

        existing_interfaces = inventory.interfaces_by_vm.get(
            netbox_vm.id,
            [],
        )

        if not validate_plan_interfaces(
            discovered_vm,
            existing_interfaces,
            counters,
            validate_interface_names=validate_interface_names,
            _interface_match=_interface_match,
        ):
            continue

        discovered_ipv4 = []

        for nic in sorted(
            discovered_vm.interfaces,
            key=lambda item: item.name,
        ):
            can_continue, existing_interface = match_plan_interface(
                discovered_vm,
                nic,
                existing_interfaces,
                counters,
                find_nic_sync_identity_matches=find_nic_sync_identity_matches,
            )
            if not can_continue:
                continue

            plan_interface_vlan(
                nic,
                inventory.vlans_by_vid,
                site,
                counters,
                _select_scoped=_select_scoped,
            )

            plan_interface_mac(
                nic,
                existing_interface,
                inventory.macs_by_address,
                counters,
                _canonical_mac=_canonical_mac,
                _assigned_object=_assigned_object,
            )

            plan_interface_ips(
                nic,
                existing_interface,
                inventory.ips_by_address,
                inventory.prefixes_by_prefix,
                site,
                counters,
                discovered_ipv4,
                _usable_address=_usable_address,
                _network_of=_network_of,
                _select_scoped=_select_scoped,
                _assigned_object=_assigned_object,
            )

        plan_primary_ipv4(
            netbox_vm,
            discovered_ipv4,
            inventory.ips_by_id,
            counters,
            _existing_primary_ipv4=_existing_primary_ipv4,
        )

    print_vm_network_plan_summary(counters)
