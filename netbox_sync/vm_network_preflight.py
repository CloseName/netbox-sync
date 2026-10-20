"""Validate the complete VM network batch before reporting or writing."""

from .netbox_record_values import object_id as _object_id
from .interface_display import interface_display_name, validate_interface_names
import ipaddress
from .network_scopes import scope_key

from .netbox_vm_metadata import (
    find_vm_sync_identity_matches,
)

from .netbox_vm_interface_metadata import (
    MANAGED_VM_INTERFACE_CUSTOM_FIELDS,
    build_nic_custom_fields,
    find_nic_sync_identity_matches,
    nic_identity_source_id,
)


class VMNetworkApplyError(RuntimeError):
    pass


class ManagedMACConflict(VMNetworkApplyError):
    """Closed operator-facing context, separate from arbitrary exception text."""

    def __init__(self, vm, nic, mac, *, duplicate=False):
        self.vm_name = vm.original_name
        self.nic_name = nic.name
        self.mac = mac
        self.duplicate = duplicate
        super().__init__(
            f"Duplicate NetBox MAC {mac}" if duplicate else f"MAC {mac} already assigned to another interface"
        )


def _canonical_mac(value):
    if not value:
        return None

    return str(value).strip().upper()


def _usable_address(value):
    try:
        interface = ipaddress.ip_interface(str(value))
    except ValueError:
        return None

    ip = interface.ip

    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return None

    return str(interface)


def _assigned_object(record):
    data = record.serialize()

    return (
        data.get("assigned_object_type"),
        data.get("assigned_object_id"),
    )


def _find_vm(
    target_vms,
    discovered_vm,
):
    matches = find_vm_sync_identity_matches(target_vms, discovered_vm)

    if len(matches) != 1:
        raise VMNetworkApplyError(
            f"Expected exactly one NetBox VM " f"for {discovered_vm.source_id}; " f"found {len(matches)}"
        )

    return matches[0]


def _interface_match(
    existing_interfaces,
    vm,
    nic,
):
    identity_matches = find_nic_sync_identity_matches(
        existing_interfaces,
        vm,
        nic,
    )

    if len(identity_matches) > 1:
        raise VMNetworkApplyError(f"Duplicate NIC identity " f"{vm.source}:" f"{nic_identity_source_id(vm, nic)}")

    if len(identity_matches) == 1:
        return identity_matches[0]

    name_matches = [
        interface
        for interface in existing_interfaces
        if (interface.name.casefold() in (nic.name.casefold(), interface_display_name(vm, nic).casefold()))
    ]

    if name_matches:
        raise VMNetworkApplyError(
            f"NIC adoption candidate exists "
            f"without sync identity: "
            f"vm={vm.original_name!r} "
            f"nic={interface_display_name(vm, nic)!r}"
        )

    return None


def _desired_interface_changes(
    existing,
    vm,
    nic,
):
    current_custom_fields = dict(
        getattr(
            existing,
            "custom_fields",
            None,
        )
        or {}
    )

    desired_custom_fields = build_nic_custom_fields(
        vm,
        nic,
        current_custom_fields,
    )

    changes = {}

    if existing.name != interface_display_name(vm, nic):
        changes["name"] = interface_display_name(vm, nic)

    data = existing.serialize()

    if data.get("enabled") is not True:
        changes["enabled"] = True

    changed_cf = any(
        current_custom_fields.get(field) != desired_custom_fields.get(field)
        for field in MANAGED_VM_INTERFACE_CUSTOM_FIELDS
    )

    if changed_cf:
        changes["custom_fields"] = desired_custom_fields

    return (
        changes,
        desired_custom_fields,
    )


def _current_primary_mac_id(interface):
    if interface is None:
        return None

    return _object_id(interface.serialize().get("primary_mac_address"))


def _current_primary_ip_id(vm):
    return _object_id(vm.serialize().get("primary_ip4"))


def _primary_ip_belongs_to_vm(ip_record, interfaces_by_id, vm_id):
    if ip_record is None:
        return False
    assigned_type, assigned_id = _assigned_object(ip_record)
    if assigned_type != "virtualization.vminterface":
        return False
    interface = interfaces_by_id.get(_object_id(assigned_id))
    if interface is None:
        return False
    return _object_id(interface.serialize().get("virtual_machine")) == vm_id


def prepare_vm_network_contexts(hosts, inventory):
    """Return checked contexts; reject conflicts before any NetBox mutation."""
    target_vms = inventory.target_vms
    interfaces_by_vm = inventory.interfaces_by_vm
    interfaces_by_id = inventory.interfaces_by_id
    macs_by_address = inventory.macs_by_address
    ips_by_address = inventory.ips_by_address
    ips_by_id = inventory.ips_by_id

    contexts = []

    discovered_macs = {}
    discovered_ips = {}

    for host in hosts:
        for vm in host.virtual_machines:
            netbox_vm = _find_vm(
                target_vms,
                vm,
            )

            existing_interfaces = interfaces_by_vm.get(
                netbox_vm.id,
                [],
            )

            validate_interface_names(
                vm,
                existing_interfaces,
                _interface_match,
                VMNetworkApplyError,
            )

            nic_names = {}

            for nic in vm.interfaces:
                nic_names.setdefault(
                    interface_display_name(vm, nic).casefold(),
                    [],
                ).append(nic)

            duplicates = [name for name, items in nic_names.items() if len(items) > 1]

            if duplicates:
                raise VMNetworkApplyError(
                    f"Duplicate discovered NIC " f"names on {vm.original_name}: " + ",".join(duplicates)
                )

            vm_context = {
                "source_vm": vm,
                "netbox_vm": netbox_vm,
                "nics": [],
                "primary_candidate": None,
                "primary_action": None,
                "primary_current": None,
            }

            vm_ipv4 = []

            for nic in vm.interfaces:
                existing = _interface_match(
                    existing_interfaces,
                    vm,
                    nic,
                )

                if existing is None:
                    desired_cf = build_nic_custom_fields(
                        vm,
                        nic,
                        {},
                    )

                    interface_changes = {}
                else:
                    (
                        interface_changes,
                        desired_cf,
                    ) = _desired_interface_changes(
                        existing,
                        vm,
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
                            vm.original_name,
                            interface_display_name(vm, nic),
                        )
                    )

                    mac_matches = macs_by_address.get(
                        mac_value,
                        [],
                    )

                    if len(mac_matches) > 1:
                        raise ManagedMACConflict(vm, nic, mac_value, duplicate=True)

                    if len(mac_matches) == 1:
                        existing_mac = mac_matches[0]

                        (
                            assigned_type,
                            assigned_id,
                        ) = _assigned_object(existing_mac)

                        allowed = assigned_type is None and assigned_id is None

                        if (
                            existing is not None
                            and assigned_type == "virtualization.vminterface"
                            and assigned_id == existing.id
                        ):
                            allowed = True

                        if not allowed:
                            raise ManagedMACConflict(vm, nic, mac_value)

                    # The interface was matched by stable source/VM/NIC identity.
                    # A changed MAC is a normal update. The desired MAC has already
                    # passed assignment checks above. Keep the old MAC record and
                    # its history; only switch this managed interface's primary.

                ip_contexts = []

                for raw_address in nic.ip_addresses:
                    address = _usable_address(raw_address)

                    if address is None:
                        continue

                    address_identity = scope_key(address, nic.ip_vrf_id)
                    discovered_ips.setdefault(
                        address_identity,
                        [],
                    ).append(
                        (
                            vm.original_name,
                            interface_display_name(vm, nic),
                        )
                    )

                    if ipaddress.ip_interface(address).version == 4:
                        vm_ipv4.append(address_identity)

                    matches = ips_by_address.get(
                        address_identity,
                        [],
                    )

                    if len(matches) > 1:
                        raise VMNetworkApplyError(f"Duplicate NetBox IP " f"{address}")

                    existing_ip = matches[0] if matches else None

                    if existing_ip is not None:
                        (
                            assigned_type,
                            assigned_id,
                        ) = _assigned_object(existing_ip)

                        allowed = assigned_type is None and assigned_id is None

                        if (
                            existing is not None
                            and assigned_type == "virtualization.vminterface"
                            and assigned_id == existing.id
                        ):
                            allowed = True

                        if not allowed:
                            raise VMNetworkApplyError(
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

                vm_context["nics"].append(
                    {
                        "source": nic,
                        "existing": existing,
                        "interface_changes": interface_changes,
                        "desired_custom_fields": desired_cf,
                        "mac_value": mac_value,
                        "existing_mac": existing_mac,
                        "ips": ip_contexts,
                    }
                )

            unique_ipv4 = sorted(set(vm_ipv4))

            if len(unique_ipv4) == 1:
                candidate = unique_ipv4[0]
                current_primary = _current_primary_ip_id(netbox_vm)
                candidate_records = ips_by_address.get(candidate, ())
                candidate_id = candidate_records[0].id if len(candidate_records) == 1 else None
                if current_primary is None:
                    primary_action = "set"
                elif current_primary == candidate_id:
                    primary_action = "match"
                else:
                    current_record = ips_by_id.get(current_primary)
                    current_address = current_record.serialize().get("address") if current_record is not None else None
                    if not _primary_ip_belongs_to_vm(
                        current_record,
                        interfaces_by_id,
                        netbox_vm.id,
                    ):
                        raise VMNetworkApplyError(
                            "Existing primary IPv4 conflicts on "
                            f"{vm.original_name}: current={current_address!r} "
                            f"discovered={candidate!r}"
                        )
                    primary_action = "preserve_manual"
                    vm_context["primary_current"] = current_address
                vm_context["primary_candidate"] = candidate
                vm_context["primary_action"] = primary_action

            contexts.append(vm_context)

    duplicate_macs = {value: locations for value, locations in discovered_macs.items() if len(locations) > 1}

    if duplicate_macs:
        raise VMNetworkApplyError("Duplicate discovered MACs: " + ",".join(sorted(duplicate_macs)))

    duplicate_ips = {value: locations for value, locations in discovered_ips.items() if len(locations) > 1}

    if duplicate_ips:
        raise VMNetworkApplyError("Duplicate discovered IPs: " + ",".join(sorted(duplicate_ips)))

    return contexts
