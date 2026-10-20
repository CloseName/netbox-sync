"""Attach managed guests to their identity-matched host; preserve cluster scope."""

from .netbox_metadata import find_sync_identity_matches
from .netbox_vm_metadata import find_vm_sync_identity_matches
from .network_scopes import object_id


def apply_guest_placement(api, hosts, config, *, confirmed=False):
    """Validate the entire placement batch before optional confirmed writes.

    Skip unmanaged hosts, process VMs before LXC on each host, and retain the
    compatibility argument config. Preview still validates. Update errors propagate
    without rollback of earlier writes; return None on successful completion.
    """
    devices = list(api.dcim.devices.all())
    vms = list(api.virtualization.virtual_machines.all())
    pending = []
    for host in hosts:
        matched = find_sync_identity_matches(devices, host)
        if not matched:
            continue  # Legacy/unmanaged hosts need explicit adoption first.
        if len(matched) != 1:
            raise ValueError("Ambiguous managed host identity")
        device = matched[0]
        for guest in [*host.virtual_machines, *host.containers]:
            vm = _find_guest(vms, guest)
            if _needs_placement(vm, guest, device, devices):
                pending.append((vm, device.id))
    if confirmed:
        for vm, identifier in pending:
            vm.update({"device": identifier})


def _find_guest(vms, guest):
    """Resolve one guest with its existing VM or LXC identity policy.

    The architecture attribute selects the LXC matcher, as in the original batch
    path. Missing and ambiguous identities share the same refusal message.
    """
    # LXC uses a separate identity builder.
    if hasattr(guest, "architecture"):
        from .netbox_lxc_metadata import find_lxc_sync_identity_matches

        matches = find_lxc_sync_identity_matches(vms, guest)
    else:
        matches = find_vm_sync_identity_matches(vms, guest)
    if len(matches) != 1:
        raise ValueError("Guest placement identity is ambiguous or missing")
    return matches[0]


def _needs_placement(vm, guest, device, devices):
    """Check ownership before cluster scope and report whether assignment changes.

    An already assigned guest skips further checks. A previous assignment is
    replaceable only when its host lists this guest's source instance; missing
    previous hosts are refused. This function never mutates records.
    """
    current = object_id(vm.serialize().get("device"))
    if current == device.id:
        return False
    if current is not None:
        previous = next((d for d in devices if d.id == current), None)
        # Never replace an unrelated manually assigned host silently.
        owner = {
            i.get("instance")
            for i in (getattr(previous, "custom_fields", {}) or {}).get("sync_identities", [])
            if isinstance(i, dict)
        }
        if guest.source_instance not in owner:
            raise ValueError("Guest has an unrelated host assignment")
    if object_id(vm.serialize().get("cluster")) != object_id(device.serialize().get("cluster")):
        raise ValueError("Guest and managed host belong to different clusters")
    return True
