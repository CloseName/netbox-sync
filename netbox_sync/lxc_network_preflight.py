"""Validate an entire LXC network batch before reporting or writing."""

from .netbox_record_values import object_id as _object_id
from .interface_display import interface_display_name, validate_interface_names
import ipaddress
from .network_scopes import scope_key, object_id as scope_object_id

from .netbox_lxc_metadata import (
    find_lxc_sync_identity_matches,
)

from .netbox_vm_interface_metadata import (
    MANAGED_VM_INTERFACE_CUSTOM_FIELDS,
    build_nic_custom_fields,
    find_nic_sync_identity_matches,
)


class LXCNetworkApplyError(RuntimeError):
    pass


def _canonical_mac(value):
    if not value:
        return None

    return str(value).strip().upper()


def _canonical_ip(value):
    return str(ipaddress.ip_interface(str(value)))


def _usable_ip(value):
    try:
        interface = ipaddress.ip_interface(str(value))
    except ValueError:
        return None

    address = interface.ip

    if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
        return None

    return str(interface)


def _assigned_object(record):
    data = record.serialize()

    return (
        data.get("assigned_object_type"),
        data.get("assigned_object_id"),
    )


def _find_lxc_vm(
    all_vms,
    container,
):
    matches = find_lxc_sync_identity_matches(all_vms, container)

    if len(matches) != 1:
        raise LXCNetworkApplyError(
            f"Expected exactly one " f"NetBox LXC object for " f"{container.source_id}; " f"found {len(matches)}"
        )

    return matches[0]


def _find_interface(
    interfaces,
    container,
    nic,
):
    identity_matches = find_nic_sync_identity_matches(
        interfaces,
        container,
        nic,
    )

    if len(identity_matches) > 1:
        raise LXCNetworkApplyError(
            f"Duplicate interface identity "
            f"on {container.original_name}:"
            f"{interface_display_name(container, nic)}"
        )

    if len(identity_matches) == 1:
        return identity_matches[0]

    name_matches = [
        interface
        for interface in interfaces
        if (interface.name.casefold() in (nic.name.casefold(), interface_display_name(container, nic).casefold()))
    ]

    if name_matches:
        raise LXCNetworkApplyError(
            f"LXC NIC adoption candidate "
            f"exists without identity: "
            f"{container.original_name}:"
            f"{interface_display_name(container, nic)}"
        )

    return None


def _interface_changes(
    interface,
    container,
    nic,
):
    current_cf = dict(
        getattr(
            interface,
            "custom_fields",
            None,
        )
        or {}
    )

    desired_cf = build_nic_custom_fields(
        container,
        nic,
        current_cf,
    )

    changes = {}

    data = interface.serialize()

    if interface.name != interface_display_name(container, nic):
        changes["name"] = interface_display_name(container, nic)

    if data.get("enabled") is not True:
        changes["enabled"] = True

    if any(current_cf.get(field) != desired_cf.get(field) for field in MANAGED_VM_INTERFACE_CUSTOM_FIELDS):
        changes["custom_fields"] = desired_cf

    return (
        changes,
        desired_cf,
    )


def _primary_mac_id(interface):
    if interface is None:
        return None

    return _object_id(interface.serialize().get("primary_mac_address"))


def _primary_ip4_id(vm):
    return _object_id(vm.serialize().get("primary_ip4"))


def prepare_lxc_network_contexts(hosts, inventory, cluster):
    """Return checked contexts using LXC-specific conflict semantics."""
    all_vms = inventory.all_vms
    interfaces_by_vm = inventory.interfaces_by_vm
    macs_by_address = inventory.macs_by_address
    ips_by_address = inventory.ips_by_address

    contexts = []

    discovered_macs = {}
    discovered_ips = {}

    for host in hosts:
        for container in host.containers:
            netbox_vm = _find_lxc_vm(
                all_vms,
                container,
            )

            vm_cluster_id = _object_id(netbox_vm.serialize().get("cluster"))

            if vm_cluster_id != cluster.id:
                raise LXCNetworkApplyError(f"LXC " f"{container.source_id} " f"is outside target cluster")

            existing_interfaces = interfaces_by_vm.get(
                netbox_vm.id,
                [],
            )

            validate_interface_names(
                container,
                existing_interfaces,
                _find_interface,
                LXCNetworkApplyError,
            )

            discovered_names = {}

            for nic in container.interfaces:
                discovered_names.setdefault(
                    interface_display_name(container, nic).casefold(),
                    [],
                ).append(nic)

            duplicates = [name for name, items in discovered_names.items() if len(items) > 1]

            if duplicates:
                raise LXCNetworkApplyError(f"Duplicate discovered " f"LXC NIC names: " + ",".join(sorted(duplicates)))

            context = {
                "container": container,
                "netbox_vm": netbox_vm,
                "nics": [],
                "primary_candidate": None,
            }

            ipv4_candidates = []

            for nic in container.interfaces:
                interface = _find_interface(
                    existing_interfaces,
                    container,
                    nic,
                )

                if interface is None:
                    changes = {}

                    desired_cf = build_nic_custom_fields(
                        container,
                        nic,
                        {},
                    )
                else:
                    (
                        changes,
                        desired_cf,
                    ) = _interface_changes(
                        interface,
                        container,
                        nic,
                    )

                mac_value = _canonical_mac(nic.mac_address)

                existing_mac = None

                if mac_value:
                    discovered_macs.setdefault(
                        mac_value,
                        [],
                    ).append(
                        (
                            container.original_name,
                            interface_display_name(container, nic),
                        )
                    )

                    matches = macs_by_address.get(
                        mac_value,
                        [],
                    )

                    if len(matches) > 1:
                        raise LXCNetworkApplyError(f"Duplicate NetBox MAC " f"{mac_value}")

                    if len(matches) == 1:
                        existing_mac = matches[0]

                        (
                            assigned_type,
                            assigned_id,
                        ) = _assigned_object(existing_mac)

                        allowed = assigned_type is None and assigned_id is None

                        if (
                            interface is not None
                            and assigned_type == "virtualization.vminterface"
                            and assigned_id == interface.id
                        ):
                            allowed = True

                        if not allowed:
                            raise LXCNetworkApplyError(
                                f"MAC {mac_value} " f"already assigned to " f"{assigned_type}:" f"{assigned_id}"
                            )

                    current_primary_mac = _primary_mac_id(interface)

                    if current_primary_mac is not None and (
                        existing_mac is None or current_primary_mac != existing_mac.id
                    ):
                        raise LXCNetworkApplyError(
                            f"Primary MAC conflict "
                            f"on "
                            f"{container.original_name}:"
                            f"{interface_display_name(container, nic)}"
                        )

                ip_contexts = []

                for raw_ip in nic.ip_addresses:
                    address = _usable_ip(raw_ip)

                    if address is None:
                        continue

                    address_identity = scope_key(address, nic.ip_vrf_id)
                    discovered_ips.setdefault(
                        address_identity,
                        [],
                    ).append(
                        (
                            container.original_name,
                            interface_display_name(container, nic),
                        )
                    )

                    if ipaddress.ip_interface(address).version == 4:
                        ipv4_candidates.append(address_identity)

                    matches = ips_by_address.get(
                        address_identity,
                        [],
                    )

                    if len(matches) > 1:
                        raise LXCNetworkApplyError(f"Duplicate NetBox IP " f"{address}")

                    existing_ip = matches[0] if matches else None

                    if existing_ip is not None:
                        (
                            assigned_type,
                            assigned_id,
                        ) = _assigned_object(existing_ip)

                        allowed = assigned_type is None and assigned_id is None

                        if (
                            interface is not None
                            and assigned_type == "virtualization.vminterface"
                            and assigned_id == interface.id
                        ):
                            allowed = True

                        if not allowed:
                            raise LXCNetworkApplyError(
                                f"IP {address} " f"already assigned to " f"{assigned_type}:" f"{assigned_id}"
                            )

                    ip_contexts.append(
                        {
                            "key": address_identity,
                            "vrf_id": nic.ip_vrf_id,
                            "address": address,
                            "existing": existing_ip,
                        }
                    )

                context["nics"].append(
                    {
                        "source": nic,
                        "existing": interface,
                        "changes": changes,
                        "desired_custom_fields": desired_cf,
                        "mac_value": mac_value,
                        "existing_mac": existing_mac,
                        "ips": ip_contexts,
                    }
                )

            unique_ipv4 = sorted(set(ipv4_candidates))

            if len(unique_ipv4) == 1:
                context["primary_candidate"] = unique_ipv4[0]

            contexts.append(context)

    duplicate_macs = [value for value, locations in discovered_macs.items() if len(locations) > 1]

    if duplicate_macs:
        raise LXCNetworkApplyError("Duplicate discovered MACs: " + ",".join(sorted(duplicate_macs)))

    duplicate_ips = [value for value, locations in discovered_ips.items() if len(locations) > 1]

    if duplicate_ips:
        raise LXCNetworkApplyError("Duplicate discovered IPs: " + ",".join(sorted(duplicate_ips)))

    return contexts
