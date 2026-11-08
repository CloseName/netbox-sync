"""NetBox VM display names are limited to 64 Unicode characters."""


def netbox_vm_name(vm):
    """Use the original VM name truncated to the legacy 64-character limit."""

    return getattr(vm, "netbox_display_name", None) or vm.original_name[:64]


def allocate_esxi_names(api, hosts, cluster_id):
    """Reserve cluster names for the selected VM identities before writing any VM."""
    from collections import defaultdict
    from hashlib import sha256
    from .netbox_record_values import object_id
    from .source_identity import SourceIdentity, virtual_machine_source_identity

    occupied = defaultdict(set)
    for record in api.virtualization.virtual_machines.all():
        if object_id(record.serialize().get("cluster")) != cluster_id:
            continue
        owners = (getattr(record, "custom_fields", None) or {}).get("sync_identities") or []
        identities = {SourceIdentity.from_record(raw) for raw in owners}
        occupied[record.name.casefold()].update(identities or {None})
    vms = sorted((vm for host in hosts for vm in host.virtual_machines), key=lambda vm: str(vm.external_id))
    source_names = {vm.original_name[:64].casefold() for vm in vms}
    for vm in vms:
        identity = virtual_machine_source_identity(vm)
        base = vm.original_name[:64]
        candidate = base
        counter = 0
        while occupied[candidate.casefold()] - {identity} or (counter and candidate.casefold() in source_names):
            token = sha256(f"{identity.instance}/{identity.external_id}/{counter}".encode()).hexdigest()[:12]
            candidate = f"{base[:49]} [{token}]"
            counter += 1
        vm.netbox_display_name = candidate
        occupied[candidate.casefold()].add(identity)
