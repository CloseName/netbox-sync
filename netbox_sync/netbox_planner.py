from .host_plan_report import report_host_plans
from .host_plan_report import print_host_plan_targets
from .host_plan_targets import prepare_host_plan_targets
from .netbox_record_values import object_id as _object_id
from .host_mapping import cluster_filter
import ipaddress
import json

import pynetbox

from .source_config import NetBoxTargetConfig

from .netbox_metadata import (
    MANAGED_DEVICE_CUSTOM_FIELDS,
    build_device_custom_fields,
    find_sync_identity_matches,
)

from .netbox_vm_planner import (
    plan_virtual_machines,
)

from .netbox_vm_network_planner import (
    plan_vm_networks,
)

from .netbox_lxc_planner import (
    plan_lxc_containers,
)


def _ip_without_prefix(value):
    if not value:
        return None

    try:
        return str(ipaddress.ip_interface(str(value)).ip)
    except ValueError:
        return str(value).split("/", 1)[0]


def _find_device_match(nb_objects: dict, host):
    """
    Device resolution policy:

      1. stable sync identity owns the object
      2. management IP and name are conflict/review evidence only
    """

    identity_matches = find_sync_identity_matches(
        nb_objects["devices"].values(),
        host,
    )

    if len(identity_matches) > 1:
        raise RuntimeError(f"Duplicate sync identity " f"{host.source}:{host.source_id} " f"in NetBox")

    if len(identity_matches) == 1:
        return (
            identity_matches[0],
            "sync_identity",
        )

    if host.management_ip:
        ip_matches = [
            device
            for device in nb_objects["devices"].values()
            if _ip_without_prefix(getattr(device, "primary_ip4", None)) == host.management_ip
        ]
        if ip_matches:
            raise RuntimeError(
                f"Device adoption candidate exists without sync identity: " f"management_ip={host.management_ip!r}"
            )

    device = nb_objects["devices"].get(host.normalized_name.lower())

    if device is not None:
        raise RuntimeError(f"Device adoption candidate exists without sync identity: " f"{host.normalized_name!r}")

    return None, None


def _get_required(endpoint, *, description: str, **filters):
    result = endpoint.get(**filters)

    if result is None:
        raise RuntimeError(f"NetBox prerequisite not found: {description} " f"filters={filters}")

    return result


def _address_ip(value):
    if not value:
        return None

    try:
        return str(ipaddress.ip_interface(str(value)).ip)
    except ValueError:
        return str(value).split("/", 1)[0]


def _find_site_vlan(nb_api, site, vlan_id):
    candidates = list(nb_api.ipam.vlans.filter(vid=vlan_id))

    site_matches = []
    global_matches = []

    for candidate in candidates:
        data = candidate.serialize()

        site_value = data.get("site")
        site_id = _object_id(site_value)

        scope_type = data.get("scope_type")
        scope_id = data.get("scope_id")

        if site_id == site.id:
            site_matches.append(candidate)
            continue

        if scope_type == "dcim.site" and scope_id == site.id:
            site_matches.append(candidate)
            continue

        if site_id is None and scope_type is None and scope_id is None:
            global_matches.append(candidate)

    if len(site_matches) == 1:
        return "match", site_matches

    if len(site_matches) > 1:
        return "conflict", site_matches

    if len(global_matches) == 1:
        return "match-global", global_matches

    if len(global_matches) > 1:
        return "conflict", global_matches

    return "missing", candidates


def _find_ip_matches(nb_api, address):
    expected = str(ipaddress.ip_interface(address))

    matches = []

    for candidate in nb_api.ipam.ip_addresses.filter(address=expected):
        try:
            actual = str(ipaddress.ip_interface(str(candidate.address)))
        except ValueError:
            actual = str(candidate.address)

        if actual == expected:
            matches.append(candidate)

    return matches


def _find_prefix_for_address(
    nb_api,
    site,
    address,
):
    network = str(ipaddress.ip_interface(address).network)

    candidates = list(nb_api.ipam.prefixes.filter(prefix=network))

    site_matches = []
    global_matches = []

    for candidate in candidates:
        data = candidate.serialize()

        site_id = _object_id(data.get("site"))

        scope_type = data.get("scope_type")

        scope_id = data.get("scope_id")

        if site_id == site.id:
            site_matches.append(candidate)
            continue

        if scope_type == "dcim.site" and scope_id == site.id:
            site_matches.append(candidate)
            continue

        if site_id is None and scope_type is None and scope_id is None:
            global_matches.append(candidate)

    if len(site_matches) == 1:
        return (
            "match",
            site_matches,
            network,
        )

    if len(site_matches) > 1:
        return (
            "conflict",
            site_matches,
            network,
        )

    if len(global_matches) == 1:
        return (
            "match-global",
            global_matches,
            network,
        )

    if len(global_matches) > 1:
        return (
            "conflict",
            global_matches,
            network,
        )

    return (
        "missing",
        candidates,
        network,
    )


def _plan_host_network(
    nb_api,
    host,
    device,
    site,
) -> None:

    print()
    print("  NETWORK")
    print("    ipam_policy=" "reference-only " "(missing VLANs/prefixes are not auto-created)")

    existing_interfaces = {}

    if device is not None:
        for interface in nb_api.dcim.interfaces.filter(device_id=device.id):
            existing_interfaces[interface.name] = interface

    management_interface = None

    for interface in host.interfaces:
        for address in interface.addresses:
            if _address_ip(address) == host.management_ip:
                management_interface = interface.name
                break

        if management_interface:
            break

    if management_interface:
        print(f"    management_interface=" f"{management_interface}")
    else:
        print("    WARNING management_interface=" "not-found")

    print()

    for interface in sorted(host.interfaces, key=lambda item: item.name):
        existing = existing_interfaces.get(interface.name)

        desired_type = "virtual" if interface.interface_type in {"bridge", "vlan"} else "other"

        if existing is None:
            print(f"    CREATE INTERFACE " f"name={interface.name} " f"type={desired_type}")
        else:
            print(f"    MATCH INTERFACE " f"id={existing.id} " f"name={interface.name}")

        print(f"      source_type=" f'{interface.interface_type or "-"}')

        print(f"      active={interface.active} " f"autostart={interface.autostart}")

        if interface.comments:
            print(f"      description=" f"{interface.comments}")

        if interface.bridge_ports:
            print("      bridge_ports=" + ",".join(interface.bridge_ports))

        if interface.vlan_aware:
            print("      vlan_aware=True")

        if interface.vlan_id is not None:
            state, vlans = _find_site_vlan(
                nb_api,
                site,
                interface.vlan_id,
            )

            if state in {"match", "match-global"}:
                vlan = vlans[0]

                print(
                    f"      MATCH VLAN "
                    f"id={vlan.id} "
                    f"vid={interface.vlan_id} "
                    f"name={vlan.name} "
                    f"scope={state}"
                )

            elif state == "conflict":
                print(f"      CONFLICT VLAN " f"vid={interface.vlan_id} " f"matches={len(vlans)}")

            else:
                print(f"      WARN VLAN " f"vid={interface.vlan_id} " f"not-found " f"action=not-created")

        for address in interface.addresses:
            (
                prefix_state,
                prefixes,
                network,
            ) = _find_prefix_for_address(
                nb_api,
                site,
                address,
            )

            if prefix_state in {
                "match",
                "match-global",
            }:
                prefix = prefixes[0]

                print(f"      MATCH PREFIX " f"id={prefix.id} " f"prefix={network} " f"scope={prefix_state}")

            elif prefix_state == "conflict":
                print(f"      CONFLICT PREFIX " f"prefix={network} " f"matches={len(prefixes)}")

            else:
                print(f"      WARN PREFIX " f"prefix={network} " f"not-found " f"action=not-created")

            matches = _find_ip_matches(
                nb_api,
                address,
            )

            if not matches:
                print(f"      CREATE IP " f"address={address}")

            elif len(matches) == 1:
                ip = matches[0]
                data = ip.serialize()

                print(f"      MATCH IP " f"id={ip.id} " f"address={address}")

                assigned_type = data.get("assigned_object_type")
                assigned_id = data.get("assigned_object_id")

                if assigned_type is not None or assigned_id is not None:
                    print(f"        currently_assigned=" f"{assigned_type}:{assigned_id}")

            else:
                print(f"      CONFLICT IP " f"address={address} " f"matches={len(matches)}")

            if _address_ip(address) == host.management_ip:
                print(f"      SET PRIMARY IPv4 " f"address={address}")

        print()


def plan_hosts(
    nb_api: pynetbox.api,
    nb_objects: dict,
    hosts: list,
    config: NetBoxTargetConfig,
) -> None:

    site, role, platform, host_types, cluster_type, cluster = prepare_host_plan_targets(
        nb_api,
        hosts,
        config,
        _get_required=_get_required,
        cluster_filter=cluster_filter,
    )

    print_host_plan_targets(
        site,
        role,
        platform,
        host_types,
        cluster_type,
        cluster,
        hosts,
        config,
    )

    report_host_plans(
        nb_api,
        nb_objects,
        hosts,
        config,
        site,
        role,
        platform,
        host_types,
        cluster,
        _find_device_match=_find_device_match,
        _plan_host_network=_plan_host_network,
        build_device_custom_fields=build_device_custom_fields,
        MANAGED_DEVICE_CUSTOM_FIELDS=MANAGED_DEVICE_CUSTOM_FIELDS,
        json=json,
        plan_virtual_machines=plan_virtual_machines,
        plan_vm_networks=plan_vm_networks,
        plan_lxc_containers=plan_lxc_containers,
    )
