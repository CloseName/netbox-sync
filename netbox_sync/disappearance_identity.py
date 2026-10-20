"""Read-only planning stages preserving existing selection and output contracts."""


def collect_discovered_identities(
    hosts,
    *,
    _local_source_id,
    vm_identity_source_id,
    virtual_machine_source_identity,
    nic_identity_source_id,
    virtual_machine_nic_source_identity,
    lxc_identity_source_id,
    lxc_source_identity,
    lxc_nic_source_identity,
):
    source_scopes = set()
    source_instances = set()
    discovered_guests = set()
    discovered_interfaces = set()

    for host in hosts:
        source = str(host.source)
        source_instances.add((source, str(host.source_instance)))

        host_source_id = _local_source_id(host)

        if host.legacy_identity_owner:
            source_scopes.add(
                (
                    source,
                    host_source_id + ":",
                )
            )

        for vm in host.virtual_machines:
            guest_identity = (
                str(vm.source),
                vm_identity_source_id(vm),
            )

            discovered_guests.add(guest_identity)
            discovered_guests.add(virtual_machine_source_identity(vm))

            for nic in vm.interfaces:
                discovered_interfaces.add(
                    (
                        str(vm.source),
                        nic_identity_source_id(
                            vm,
                            nic,
                        ),
                    )
                )
                discovered_interfaces.add(virtual_machine_nic_source_identity(vm, nic))

        for container in host.containers:
            guest_identity = (
                str(container.source),
                lxc_identity_source_id(container),
            )

            discovered_guests.add(guest_identity)
            discovered_guests.add(lxc_source_identity(container))

            for nic in container.interfaces:
                discovered_interfaces.add(
                    (
                        str(container.source),
                        nic_identity_source_id(
                            container,
                            nic,
                        ),
                    )
                )
                discovered_interfaces.add(lxc_nic_source_identity(container, nic))

    return source_scopes, source_instances, discovered_guests, discovered_interfaces


def build_managed_identity_resolver(source_scopes, source_instances, *, _identities, _v2_identities):
    def managed_identity(
        custom_fields,
    ):
        v2_matches = [
            identity
            for identity in _v2_identities(custom_fields)
            if (identity.type, identity.instance) in source_instances
        ]

        if len(v2_matches) > 1:
            raise RuntimeError("Object has multiple managed Proxmox v2 identities: " + repr(v2_matches))

        if v2_matches:
            return v2_matches[0]

        matches = []

        for identity in _identities(custom_fields):
            source, source_id = identity

            for (
                scoped_source,
                prefix,
            ) in source_scopes:
                if source == scoped_source and source_id.startswith(prefix):
                    matches.append(identity)

        if len(matches) > 1:
            raise RuntimeError("Object has multiple managed " "Proxmox identities: " + repr(matches))

        if not matches:
            return None

        return matches[0]

    return managed_identity
