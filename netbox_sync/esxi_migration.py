"""Read-only ESXi migration planning for legacy objects and interfaces."""

import ipaddress
import re
from dataclasses import dataclass, replace
from enum import Enum

from .esxi_adoption import (
    AdoptionClassification,
    build_esxi_adoption_plan,
)
from .netbox_vm_interface_metadata import find_nic_sync_identity_matches
from .source_identity import host_source_identity, virtual_machine_source_identity


class ObjectMigrationClassification(str, Enum):
    """Migration classification for a discovered host or VM."""

    MANAGED = 'MANAGED'
    NEW = 'NEW'
    REVIEW_REQUIRED = 'REVIEW_REQUIRED'
    SAFE_LEGACY_CANDIDATE = 'SAFE_LEGACY_CANDIDATE'
    AMBIGUOUS = 'AMBIGUOUS'


class InterfaceMigrationClassification(str, Enum):
    """Read-only correlation state for one discovered interface."""

    MATCH_EXISTING = 'MATCH_EXISTING'
    SAFE_RENAME_OR_REUSE_CANDIDATE = 'SAFE_RENAME_OR_REUSE_CANDIDATE'
    CREATE = 'CREATE'
    AMBIGUOUS = 'AMBIGUOUS'
    CONFLICT = 'CONFLICT'


@dataclass(frozen=True)
class ObjectCandidate:
    """Legacy NetBox object evidence retained for operator review."""

    object_id: object
    object_name: str
    signals: tuple[str, ...]
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class InterfaceCandidate:
    """Existing interface and its current network ownership evidence."""

    parent_id: object
    parent_name: str
    interface_id: object
    interface_name: str
    signals: tuple[str, ...]
    conflicts: tuple[str, ...]
    current_ips: tuple[str, ...]
    current_macs: tuple[str, ...]
    current_ip_assignments: tuple[tuple[object, str], ...] = ()
    current_mac_assignments: tuple[tuple[object, str], ...] = ()


@dataclass(frozen=True)
class InterfaceMigrationItem:
    """Correlation result for one discovered ESXi interface."""

    discovered_name: str
    discovered_external_id: str | None
    discovered_ips: tuple[str, ...]
    discovered_mac: str | None
    classification: InterfaceMigrationClassification
    candidates: tuple[InterfaceCandidate, ...] = ()
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class HostMigrationItem:
    """Migration result for one discovered ESXi host."""

    discovered_name: str
    external_id: str
    classification: ObjectMigrationClassification
    candidates: tuple[ObjectCandidate, ...]
    interfaces: tuple[InterfaceMigrationItem, ...]


@dataclass(frozen=True)
class VirtualMachineMigrationItem:
    """Migration result for one discovered ESXi VM."""

    discovered_name: str
    external_id: str
    classification: ObjectMigrationClassification
    candidates: tuple[ObjectCandidate, ...]
    interfaces: tuple[InterfaceMigrationItem, ...]


@dataclass(frozen=True)
class EsxiMigrationPlan:
    """Immutable structured ESXi migration preflight result."""

    source_instance: str
    site_id: object
    cluster_id: object
    hosts: tuple[HostMigrationItem, ...]
    virtual_machines: tuple[VirtualMachineMigrationItem, ...]


def _object_id(value):
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, dict):
        return value.get('id')
    return getattr(value, 'id', None)


def _serialized(record):
    serialize = getattr(record, 'serialize', None)
    return serialize() if callable(serialize) else vars(record)


def _canonical_ip(value):
    if value is None:
        return None
    try:
        address = ipaddress.ip_interface(str(value)).ip
    except ValueError:
        return None
    if (
            address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
    ):
        return None
    return str(address)


def _canonical_mac(value):
    if not value:
        return None
    compact = re.sub(r'[^0-9A-Fa-f]', '', str(value))
    if len(compact) != 12:
        return None
    return ':'.join(
        compact[index:index + 2].upper()
        for index in range(0, 12, 2)
    )


def _record_name(record):
    return str(getattr(record, 'name', f'id={record.id}'))


class _NetworkOwnership:
    """Snapshot current NetBox interface and network assignments."""

    def __init__(self, nb_api):
        self.interfaces = {
            'host': list(nb_api.dcim.interfaces.all()),
            'vm': list(nb_api.virtualization.interfaces.all()),
        }
        self.parents = {
            'host': {item.id: item for item in nb_api.dcim.devices.all()},
            'vm': {
                item.id: item
                for item in nb_api.virtualization.virtual_machines.all()
            },
        }
        self.by_id = {
            kind: {item.id: item for item in records}
            for kind, records in self.interfaces.items()
        }
        self.ip_assignments = {}
        self.mac_assignments = {}
        for record in nb_api.ipam.ip_addresses.all():
            data = _serialized(record)
            address = _canonical_ip(data.get('address'))
            assigned_type = data.get('assigned_object_type')
            assigned_id = _object_id(data.get('assigned_object_id'))
            if (
                    address
                    and (assigned_type is not None or assigned_id is not None)
            ):
                self.ip_assignments.setdefault(address, []).append((
                    assigned_type,
                    assigned_id,
                    record.id,
                ))
        for record in nb_api.dcim.mac_addresses.all():
            data = _serialized(record)
            address = _canonical_mac(data.get('mac_address'))
            assigned_type = data.get('assigned_object_type')
            assigned_id = _object_id(data.get('assigned_object_id'))
            if (
                    address
                    and (assigned_type is not None or assigned_id is not None)
            ):
                self.mac_assignments.setdefault(address, []).append((
                    assigned_type,
                    assigned_id,
                    record.id,
                ))

    @staticmethod
    def _relation(kind):
        return 'device' if kind == 'host' else 'virtual_machine'

    @staticmethod
    def _assigned_type(kind):
        return 'dcim.interface' if kind == 'host' else 'virtualization.vminterface'

    def owned_interfaces(self, kind, parent_id):
        """Return interfaces currently belonging to the selected parent."""

        relation = self._relation(kind)
        return tuple(
            interface
            for interface in self.interfaces[kind]
            if _object_id(_serialized(interface).get(relation)) == parent_id
        )

    def _current_network(self, kind, interface):
        expected_type = self._assigned_type(kind)
        ips = {
            address
            for address, assignments in self.ip_assignments.items()
            if any(
                assigned_type == expected_type and assigned_id == interface.id
                for assigned_type, assigned_id, _ in assignments
            )
        }
        macs = {
            address
            for address, assignments in self.mac_assignments.items()
            if any(
                assigned_type == expected_type and assigned_id == interface.id
                for assigned_type, assigned_id, _ in assignments
            )
        }
        return tuple(sorted(ips)), tuple(sorted(macs))

    def current_assignments(self, kind, interface):
        """Return immutable record-id/address evidence for one interface."""

        expected_type = self._assigned_type(kind)
        ips = {
            (record_id, address)
            for address, assignments in self.ip_assignments.items()
            for assigned_type, assigned_id, record_id in assignments
            if assigned_type == expected_type and assigned_id == interface.id
        }
        macs = {
            (record_id, address)
            for address, assignments in self.mac_assignments.items()
            for assigned_type, assigned_id, record_id in assignments
            if assigned_type == expected_type and assigned_id == interface.id
        }
        return (
            tuple(sorted(ips, key=lambda item: (str(item[0]), item[1]))),
            tuple(sorted(macs, key=lambda item: (str(item[0]), item[1]))),
        )

    def candidate(self, kind, interface, signals, conflicts=()):
        """Build immutable evidence for an existing NetBox interface."""

        relation = self._relation(kind)
        parent_id = _object_id(_serialized(interface).get(relation))
        parent = self.parents[kind].get(parent_id)
        ips, macs = self._current_network(kind, interface)
        ip_assignments, mac_assignments = self.current_assignments(
            kind, interface,
        )
        return InterfaceCandidate(
            parent_id=parent_id,
            parent_name=_record_name(parent) if parent else f'id={parent_id}',
            interface_id=interface.id,
            interface_name=_record_name(interface),
            signals=tuple(sorted(signals)),
            conflicts=tuple(sorted(conflicts)),
            current_ips=ips,
            current_macs=macs,
            current_ip_assignments=ip_assignments,
            current_mac_assignments=mac_assignments,
        )


def _discovered_interface_network(interface, extra_ips=()):
    ips = {
        address
        for value in (*getattr(interface, 'ip_addresses', ()), *extra_ips)
        if (address := _canonical_ip(value)) is not None
    }
    if hasattr(interface, 'addresses'):
        ips.update(
            address
            for value in interface.addresses
            if (address := _canonical_ip(value)) is not None
        )
    mac = _canonical_mac(getattr(interface, 'mac_address', None))
    return tuple(sorted(ips)), mac


def _network_hits(ownership, kind, discovered_ips, discovered_mac):
    expected_type = ownership._assigned_type(kind)  # pylint: disable=protected-access
    hits = {}
    conflicts = []
    duplicate = False
    values = [
        ('ip', address, ownership.ip_assignments.get(address, ()))
        for address in discovered_ips
    ]
    if discovered_mac:
        values.append((
            'mac',
            discovered_mac,
            ownership.mac_assignments.get(discovered_mac, ()),
        ))
    for signal_type, value, assignments in values:
        if len(assignments) > 1:
            duplicate = True
        for assigned_type, interface_id, record_id in assignments:
            signal = f'{signal_type}:{value}'
            if assigned_type != expected_type or interface_id is None:
                conflicts.append(
                    f'{signal} assigned to {assigned_type}:{interface_id}'
                )
                continue
            interface = ownership.by_id[kind].get(interface_id)
            if interface is None:
                conflicts.append(
                    f'{signal} references missing interface id={interface_id}'
                )
                continue
            entry = hits.setdefault(interface_id, {
                'interface': interface,
                'signals': set(),
                'records': set(),
            })
            entry['signals'].add(signal)
            entry['records'].add((signal_type, record_id))
    return hits, tuple(sorted(set(conflicts))), duplicate


def _correlate_interface(
        ownership,
        kind,
        parent,
        discovered,
        *,
        extra_ips=(),
        identity_matches=(),
):
    discovered_ips, discovered_mac = _discovered_interface_network(
        discovered, extra_ips,
    )
    if len(identity_matches) > 1:
        candidates = tuple(
            ownership.candidate(kind, item, ('source_identity_v2',))
            for item in identity_matches
        )
        return InterfaceMigrationItem(
            discovered_name=discovered.name,
            discovered_external_id=getattr(discovered, 'external_id', None),
            discovered_ips=discovered_ips,
            discovered_mac=discovered_mac,
            classification=InterfaceMigrationClassification.AMBIGUOUS,
            candidates=candidates,
            conflicts=('duplicate interface identity',),
        )
    if len(identity_matches) == 1:
        candidate = ownership.candidate(
            kind, identity_matches[0], ('source_identity_v2',),
        )
        return InterfaceMigrationItem(
            discovered_name=discovered.name,
            discovered_external_id=getattr(discovered, 'external_id', None),
            discovered_ips=discovered_ips,
            discovered_mac=discovered_mac,
            classification=InterfaceMigrationClassification.MATCH_EXISTING,
            candidates=(candidate,),
        )

    hits, conflicts, duplicate = _network_hits(
        ownership, kind, discovered_ips, discovered_mac,
    )
    owned = {item.id for item in ownership.owned_interfaces(kind, parent.id)}
    foreign = [entry for key, entry in hits.items() if key not in owned]
    local = [entry for key, entry in hits.items() if key in owned]
    all_candidates = tuple(
        ownership.candidate(
            kind,
            entry['interface'],
            entry['signals'],
            ('foreign_parent',) if entry in foreign else (),
        )
        for entry in (*local, *foreign)
    )
    if conflicts or foreign:
        return InterfaceMigrationItem(
            discovered_name=discovered.name,
            discovered_external_id=getattr(discovered, 'external_id', None),
            discovered_ips=discovered_ips,
            discovered_mac=discovered_mac,
            classification=InterfaceMigrationClassification.CONFLICT,
            candidates=all_candidates,
            conflicts=conflicts or ('network evidence belongs to another object',),
        )
    if duplicate or len(local) > 1:
        return InterfaceMigrationItem(
            discovered_name=discovered.name,
            discovered_external_id=getattr(discovered, 'external_id', None),
            discovered_ips=discovered_ips,
            discovered_mac=discovered_mac,
            classification=InterfaceMigrationClassification.AMBIGUOUS,
            candidates=all_candidates,
            conflicts=('duplicate network evidence',),
        )
    if len(local) == 1:
        entry = local[0]
        candidate = ownership.candidate(
            kind, entry['interface'], entry['signals'],
        )
        classification = (
            InterfaceMigrationClassification.MATCH_EXISTING
            if candidate.interface_name.casefold() == discovered.name.casefold()
            else InterfaceMigrationClassification.SAFE_RENAME_OR_REUSE_CANDIDATE
        )
        return InterfaceMigrationItem(
            discovered_name=discovered.name,
            discovered_external_id=getattr(discovered, 'external_id', None),
            discovered_ips=discovered_ips,
            discovered_mac=discovered_mac,
            classification=classification,
            candidates=(candidate,),
        )

    exact_names = [
        item for item in ownership.owned_interfaces(kind, parent.id)
        if _record_name(item).casefold() == discovered.name.casefold()
    ]
    if len(exact_names) == 1:
        candidate = ownership.candidate(kind, exact_names[0], ('exact_name',))
        return InterfaceMigrationItem(
            discovered_name=discovered.name,
            discovered_external_id=getattr(discovered, 'external_id', None),
            discovered_ips=discovered_ips,
            discovered_mac=discovered_mac,
            classification=InterfaceMigrationClassification.MATCH_EXISTING,
            candidates=(candidate,),
        )
    if len(exact_names) > 1:
        return InterfaceMigrationItem(
            discovered_name=discovered.name,
            discovered_external_id=getattr(discovered, 'external_id', None),
            discovered_ips=discovered_ips,
            discovered_mac=discovered_mac,
            classification=InterfaceMigrationClassification.AMBIGUOUS,
            candidates=tuple(
                ownership.candidate(kind, item, ('exact_name',))
                for item in exact_names
            ),
            conflicts=('duplicate interface names',),
        )
    return InterfaceMigrationItem(
        discovered_name=discovered.name,
        discovered_external_id=getattr(discovered, 'external_id', None),
        discovered_ips=discovered_ips,
        discovered_mac=discovered_mac,
        classification=InterfaceMigrationClassification.CREATE,
    )


def _mark_shared_interface_claims(items):
    claims = {}
    for index, item in enumerate(items):
        if item.classification not in {
                InterfaceMigrationClassification.MATCH_EXISTING,
                InterfaceMigrationClassification.SAFE_RENAME_OR_REUSE_CANDIDATE,
        }:
            continue
        for candidate in item.candidates:
            claims.setdefault(candidate.interface_id, []).append(index)
    ambiguous = {
        index
        for indexes in claims.values()
        if len(set(indexes)) > 1
        for index in indexes
    }
    return tuple(
        replace(
            item,
            classification=InterfaceMigrationClassification.AMBIGUOUS,
            conflicts=tuple(sorted({*item.conflicts, 'shared interface claim'})),
        )
        if index in ambiguous
        else item
        for index, item in enumerate(items)
    )


_OBJECT_CLASSIFICATIONS = {
    AdoptionClassification.RETAINED_NAME: ObjectMigrationClassification.REVIEW_REQUIRED,
    AdoptionClassification.MANAGED: ObjectMigrationClassification.MANAGED,
    AdoptionClassification.SAFE_ADOPTION_CANDIDATE:
        ObjectMigrationClassification.SAFE_LEGACY_CANDIDATE,
    AdoptionClassification.REVIEW_REQUIRED:
        ObjectMigrationClassification.REVIEW_REQUIRED,
    AdoptionClassification.AMBIGUOUS:
        ObjectMigrationClassification.AMBIGUOUS,
    AdoptionClassification.UNMATCHED: ObjectMigrationClassification.NEW,
}


def _object_candidates(item):
    return tuple(
        ObjectCandidate(
            object_id=candidate.object_id,
            object_name=candidate.object_name,
            signals=candidate.signals,
            conflicts=candidate.conflicts,
        )
        for candidate in item.candidates
    )


def build_esxi_migration_plan(nb_api, hosts, config):
    """Build an immutable migration diagnosis without writing to NetBox."""

    adoption = build_esxi_adoption_plan(nb_api, hosts, config)
    adoption_by_identity = {item.identity: item for item in adoption.items}
    ownership = _NetworkOwnership(nb_api)
    host_results = []
    vm_results = []

    for host in hosts:
        host_item = adoption_by_identity[host_source_identity(host)]
        host_interfaces = []
        if host_item.classification == AdoptionClassification.MANAGED:
            device = nb_api.dcim.devices.get(id=host_item.selected_object_id)
            for interface in host.interfaces:
                extra_ips = (
                    (host.management_ip,)
                    if interface.management and host.management_ip
                    else ()
                )
                host_interfaces.append(_correlate_interface(
                    ownership,
                    'host',
                    device,
                    interface,
                    extra_ips=extra_ips,
                ))
        host_results.append(HostMigrationItem(
            discovered_name=host.original_name,
            external_id=host.source_id,
            classification=_OBJECT_CLASSIFICATIONS[host_item.classification],
            candidates=_object_candidates(host_item),
            interfaces=_mark_shared_interface_claims(host_interfaces),
        ))

        for vm in host.virtual_machines:
            vm_item = adoption_by_identity[virtual_machine_source_identity(vm)]
            vm_interfaces = []
            if vm_item.classification == AdoptionClassification.MANAGED:
                netbox_vm = nb_api.virtualization.virtual_machines.get(
                    id=vm_item.selected_object_id
                )
                existing = ownership.owned_interfaces('vm', netbox_vm.id)
                for interface in vm.interfaces:
                    identity_matches = find_nic_sync_identity_matches(
                        existing, vm, interface,
                    )
                    vm_interfaces.append(_correlate_interface(
                        ownership,
                        'vm',
                        netbox_vm,
                        interface,
                        identity_matches=identity_matches,
                    ))
            vm_results.append(VirtualMachineMigrationItem(
                discovered_name=vm.original_name,
                external_id=str(vm.external_id or vm.vmid),
                classification=_OBJECT_CLASSIFICATIONS[vm_item.classification],
                candidates=_object_candidates(vm_item),
                interfaces=_mark_shared_interface_claims(vm_interfaces),
            ))

    return EsxiMigrationPlan(
        source_instance=config.source_instance,
        site_id=adoption.site_id,
        cluster_id=adoption.cluster_id,
        hosts=tuple(host_results),
        virtual_machines=tuple(vm_results),
    )
