"""Read-only planning stages preserving existing selection and output contracts."""

from typing import NamedTuple


class _DiscoveredIdentities(NamedTuple):
    """Keep legacy scopes and discovered object sets together during collection."""

    scopes: set
    instances: set
    guests: set
    interfaces: set


class _GuestIdentityRules(NamedTuple):
    """Retain provider-specific guest and interface identity callbacks."""

    legacy_guest: object
    guest: object
    legacy_nic: object
    nic: object


def _collect_guest_identities(guest, discovered, rules):
    """Collect one guest and its NICs in legacy-then-v2 callback order."""
    discovered.guests.add((str(guest.source), rules.legacy_guest(guest)))
    discovered.guests.add(rules.guest(guest))
    for nic in guest.interfaces:
        discovered.interfaces.add((str(guest.source), rules.legacy_nic(guest, nic)))
        discovered.interfaces.add(rules.nic(guest, nic))


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
    """Collect legacy and v2 guest/NIC identities with their permitted source scopes."""

    discovered = _DiscoveredIdentities(set(), set(), set(), set())
    for host in hosts:
        source = str(host.source)
        discovered.instances.add((source, str(host.source_instance)))
        host_source_id = _local_source_id(host)
        if host.legacy_identity_owner:
            discovered.scopes.add((source, host_source_id + ":"))
        for vm in host.virtual_machines:
            _collect_guest_identities(
                vm,
                discovered,
                _GuestIdentityRules(
                    vm_identity_source_id,
                    virtual_machine_source_identity,
                    nic_identity_source_id,
                    virtual_machine_nic_source_identity,
                ),
            )
        for container in host.containers:
            _collect_guest_identities(
                container,
                discovered,
                _GuestIdentityRules(
                    lxc_identity_source_id, lxc_source_identity, nic_identity_source_id, lxc_nic_source_identity
                ),
            )
    return tuple(discovered)


def build_managed_identity_resolver(source_scopes, source_instances, *, _identities, _v2_identities):
    """Build a resolver that prefers unique in-scope v2 identities over legacy identities."""

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
