from .lxc_apply_writes import write_lxc_containers
from .lxc_apply_report import report_lxc_precheck
from .lxc_apply_preflight import prepare_lxc_contexts
from .lxc_apply_inventory import prepare_lxc_apply_inventory
from .host_mapping import cluster_filter
from .netbox_lxc_metadata import (
    MANAGED_LXC_CUSTOM_FIELDS,
    build_lxc_custom_fields,
    find_lxc_sync_identity_matches,
)


class LXCApplyError(RuntimeError):
    pass


def _status(value):
    mapping = {
        "running": "active",
        "stopped": "offline",
        "paused": "paused",
    }

    if value not in mapping:
        raise LXCApplyError(f"Unsupported LXC status: {value!r}")

    return mapping[value]


def _disk_mib(container):
    return sum(disk.size_bytes for disk in container.disks) // 1024**2


def _desired_fields(
    container,
    cluster,
    existing=None,
):
    current_cf = {}

    if existing is not None:
        current_cf = dict(
            getattr(
                existing,
                "custom_fields",
                None,
            )
            or {}
        )

    custom_fields = build_lxc_custom_fields(
        container,
        current_cf,
    )

    return {
        "name": container.original_name,
        "cluster": cluster.id,
        "status": _status(container.status),
        "vcpus": container.vcpus,
        "memory": container.memory_bytes // 1024**2,
        "disk": _disk_mib(container),
        "start_on_boot": ("on" if container.autostart else "off"),
        "custom_fields": custom_fields,
    }


def _find_identity_matches(
    all_vms,
    container,
):
    return find_lxc_sync_identity_matches(all_vms, container)


def _changes(
    existing,
    desired,
):
    data = existing.serialize()

    result = {}

    scalar_fields = (
        "name",
        "status",
        "vcpus",
        "memory",
        "disk",
        "start_on_boot",
    )

    for field in scalar_fields:
        if data.get(field) != desired[field]:
            result[field] = desired[field]

    current_cluster = data.get("cluster")

    if isinstance(
        current_cluster,
        dict,
    ):
        current_cluster = current_cluster.get("id")

    if current_cluster != desired["cluster"]:
        result["cluster"] = desired["cluster"]

    current_cf = dict(
        getattr(
            existing,
            "custom_fields",
            None,
        )
        or {}
    )

    desired_cf = desired["custom_fields"]

    if any(current_cf.get(field) != desired_cf.get(field) for field in MANAGED_LXC_CUSTOM_FIELDS):
        result["custom_fields"] = desired_cf

    return result


def apply_lxc_containers(
    nb_api,
    hosts,
    config,
    *,
    confirmed=False,
):
    inventory = prepare_lxc_apply_inventory(
        nb_api,
        config,
        cluster_filter=cluster_filter,
        LXCApplyError=LXCApplyError,
    )
    site = inventory.site
    cluster = inventory.cluster
    all_vms = inventory.all_vms
    target_vms = inventory.target_vms

    contexts = prepare_lxc_contexts(
        hosts,
        all_vms,
        target_vms,
        cluster,
        _find_identity_matches=_find_identity_matches,
        _desired_fields=_desired_fields,
        _changes=_changes,
        LXCApplyError=LXCApplyError,
    )

    report_lxc_precheck(
        site,
        cluster,
        contexts,
    )

    if not confirmed:
        print("APPLY_CONFIRM=LXC_WRITE " "is not set.")

        print("No changes were written " "to NetBox.")

        return

    write_lxc_containers(
        nb_api,
        contexts,
    )
