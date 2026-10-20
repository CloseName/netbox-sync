from .host_apply_writes import write_hosts
from .host_precheck_report import print_host_precheck
from .host_apply_preflight import prepare_host_context
from .host_apply_targets import prepare_host_apply_targets
from .netbox_record_values import object_id as _object_id, choice_value as _choice_value
import ipaddress

from .netbox_metadata import (
    MANAGED_DEVICE_CUSTOM_FIELDS,
    build_device_custom_fields,
    find_sync_identity_matches,
)


class HostApplyError(RuntimeError):
    pass


def _canonical_address(value):
    return str(ipaddress.ip_interface(str(value)))


def _address_ip(value):
    return str(ipaddress.ip_interface(str(value)).ip)


def _required(endpoint, description, **filters):
    result = endpoint.get(**filters)

    if result is None:
        raise HostApplyError(f"NetBox prerequisite not found: " f"{description} filters={filters}")

    return result


def _resolve_cluster(
    nb_api,
    site,
    cluster_type,
    cluster_name,
    cluster_id=None,
):
    matches = []

    for cluster in nb_api.virtualization.clusters.filter(
        **({"id": cluster_id} if cluster_id else {"name": cluster_name})
    ):
        data = cluster.serialize()

        if (
            _object_id(data.get("type")) == cluster_type.id
            and data.get("scope_type") == "dcim.site"
            and data.get("scope_id") == site.id
        ):
            matches.append(cluster)

    if len(matches) != 1:
        raise HostApplyError(f"Expected exactly one target cluster " f"{cluster_name!r}; found {len(matches)}")

    return matches[0]


def _resolve_device(
    nb_api,
    host,
    site,
):
    devices = list(nb_api.dcim.devices.all())

    # 1. Stable source identity
    identity_matches = find_sync_identity_matches(devices, host)

    if len(identity_matches) > 1:
        raise HostApplyError(
            f"Duplicate sync identity " f"{host.source}:{host.source_id} " f"matches={len(identity_matches)}"
        )

    if len(identity_matches) == 1:
        device = identity_matches[0]
        reason = "sync_identity"

    else:
        # 2. Management IP
        ip_matches = []

        if host.management_ip:
            for candidate in devices:
                primary = getattr(
                    candidate,
                    "primary_ip4",
                    None,
                )

                if primary is None:
                    continue

                try:
                    current_ip = _address_ip(primary)
                except ValueError:
                    continue

                if current_ip == host.management_ip:
                    ip_matches.append(candidate)

        if len(ip_matches) > 1:
            raise HostApplyError(f"Management IP conflict: " f"{host.management_ip} " f"matches={len(ip_matches)}")

        if ip_matches:
            raise HostApplyError(
                f"Device adoption candidate exists without sync identity: " f"management_ip={host.management_ip!r}"
            )

        # A name is useful conflict evidence, never ownership evidence.
        name_matches = [
            candidate for candidate in devices if candidate.name.casefold() == host.normalized_name.casefold()
        ]

        if len(name_matches) > 1:
            raise HostApplyError(f"Device name conflict: " f"{host.normalized_name!r} " f"matches={len(name_matches)}")

        if name_matches:
            raise HostApplyError(
                f"Device adoption candidate exists without sync identity: " f"{host.normalized_name!r}"
            )

        return None, None

    data = device.serialize()

    existing_site = _object_id(data.get("site"))

    if existing_site != site.id:
        raise HostApplyError(
            f"Device {device.name!r} "
            f"matched by {reason} but "
            f"is outside target site: "
            f"site_id={existing_site}"
        )

    return device, reason


def _load_existing_interfaces(
    nb_api,
    device,
):
    if device is None:
        return {}

    result = {}

    for interface in nb_api.dcim.interfaces.filter(device_id=device.id):
        if interface.name in result:
            raise HostApplyError(f"Duplicate interface " f"{interface.name!r} " f"on device id={device.id}")

        result[interface.name] = interface

    return result


def _find_ip_matches(
    nb_api,
    address,
):
    canonical = _canonical_address(address)

    result = []

    for candidate in nb_api.ipam.ip_addresses.filter(address=canonical):
        if _canonical_address(candidate.address) == canonical and getattr(candidate, "vrf", None) is None:
            result.append(candidate)

    return result


def _management_binding(host):
    matches = []

    for interface in host.interfaces:
        for address in interface.addresses:
            if _address_ip(address) == host.management_ip:
                matches.append(
                    (
                        interface.name,
                        _canonical_address(address),
                    )
                )

    if len(matches) != 1:
        raise HostApplyError(
            f"Expected exactly one management " f"address for {host.normalized_name}; " f"found {len(matches)}"
        )

    return matches[0]


def _desired_interface_type(
    interface,
):
    if interface.interface_type in {
        "bridge",
        "vlan",
    }:
        return "virtual"

    return "other"


def _managed_metadata(
    host,
    device,
):
    existing = {}

    if device is not None:
        existing = dict(
            getattr(
                device,
                "custom_fields",
                None,
            )
            or {}
        )

    desired = build_device_custom_fields(
        host,
        existing,
    )

    changed = [
        field_name
        for field_name in MANAGED_DEVICE_CUSTOM_FIELDS
        if (existing.get(field_name) != desired.get(field_name))
    ]

    return desired, changed


def _preflight_host(
    nb_api,
    host,
    site,
    *,
    host_networking=True,
):
    return prepare_host_context(
        nb_api,
        host,
        site,
        host_networking=host_networking,
        _resolve_device=_resolve_device,
        _managed_metadata=_managed_metadata,
        _load_existing_interfaces=_load_existing_interfaces,
        _management_binding=_management_binding,
        _canonical_address=_canonical_address,
        _find_ip_matches=_find_ip_matches,
        HostApplyError=HostApplyError,
    )


def _device_changes(
    device,
    *,
    site,
    role,
    platform,
    device_type,
    cluster,
    desired_custom_fields,
    changed_custom_fields,
):
    data = device.serialize()
    changes = {}

    expected = {
        "site": site.id,
        "role": role.id,
        "platform": platform.id,
        "device_type": device_type.id,
        "cluster": cluster.id,
    }
    from .selectel_authority import owned_fields

    protected = owned_fields(data.get("custom_fields"))
    if "site_id" in protected:
        expected.pop("site")

    for field, desired_id in expected.items():
        if _object_id(data.get(field)) != desired_id:
            changes[field] = desired_id

    if changed_custom_fields:
        # Send the complete current+managed CF map so
        # existing manual fields are preserved.
        changes["custom_fields"] = desired_custom_fields

    return changes


def _interface_changes(
    interface,
    discovered,
):
    data = interface.serialize()

    desired_type = _desired_interface_type(discovered)

    changes = {}

    current_type = _choice_value(data.get("type"))

    if current_type != desired_type:
        changes["type"] = desired_type

    desired_enabled = bool(discovered.autostart)

    if bool(data.get("enabled")) != desired_enabled:
        changes["enabled"] = desired_enabled

    if discovered.comments is not None:
        current_description = data.get("description") or ""

        if current_description != discovered.comments:
            changes["description"] = discovered.comments

    return changes


def apply_hosts(
    nb_api,
    hosts,
    config,
    *,
    confirmed=False,
    host_networking=True,
):
    targets = prepare_host_apply_targets(
        nb_api,
        hosts,
        config,
        _required=_required,
        _resolve_cluster=_resolve_cluster,
    )
    site = targets.site
    role = targets.role
    platform = targets.platform
    host_types = targets.host_types
    cluster = targets.cluster

    contexts = []

    for host in hosts:
        contexts.append(
            _preflight_host(
                nb_api,
                host,
                site,
                host_networking=host_networking,
            )
        )

    print_host_precheck(contexts, site, cluster, host_types)

    if not confirmed:
        print("APPLY_CONFIRM=HOST_WRITE " "is not set.")
        print("No changes were written " "to NetBox.")
        return

    write_hosts(
        nb_api,
        contexts,
        site,
        role,
        platform,
        cluster,
        host_types,
        host_networking=host_networking,
        _device_changes=_device_changes,
        _load_existing_interfaces=_load_existing_interfaces,
        _desired_interface_type=_desired_interface_type,
        _interface_changes=_interface_changes,
        _find_ip_matches=_find_ip_matches,
        _object_id=_object_id,
        HostApplyError=HostApplyError,
    )
