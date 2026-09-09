"""Read-only legacy ESXi adoption planning and confirmed metadata adoption."""
from .host_mapping import cluster_filter

import ipaddress
import json
import re
from dataclasses import dataclass, replace
from enum import Enum

from .source_identity import (
    V2_IDENTITY_MATCH,
    host_source_identity,
    merge_original_name,
    merge_source_identities,
    source_identity_match_rank,
    virtual_machine_source_identity,
)


class AdoptionClassification(str, Enum):
    """Fail-closed classification of one discovered ESXi object."""

    MANAGED = 'MANAGED'
    SAFE_ADOPTION_CANDIDATE = 'SAFE_ADOPTION_CANDIDATE'
    REVIEW_REQUIRED = 'REVIEW_REQUIRED'
    AMBIGUOUS = 'AMBIGUOUS'
    UNMATCHED = 'UNMATCHED'


class EsxiAdoptionError(RuntimeError):
    """An adoption plan or confirmed adoption failed safely."""


@dataclass(frozen=True)
class AdoptionEvidence:
    """Immutable evidence connecting one discovered and NetBox object."""

    object_id: object
    object_name: str
    signals: tuple[str, ...]
    conflicts: tuple[str, ...]
    custom_fields_snapshot: str


@dataclass(frozen=True)
class EsxiAdoptionItem:
    """Immutable preflight result for one discovered host or VM."""

    object_kind: str
    source_name: str
    identity: object
    classification: AdoptionClassification
    candidates: tuple[AdoptionEvidence, ...] = ()
    selected_object_id: object = None


@dataclass(frozen=True)
class EsxiAdoptionPlan:
    """Immutable, target-scoped ESXi adoption plan."""

    source_instance: str
    site_id: object
    cluster_id: object
    items: tuple[EsxiAdoptionItem, ...]


def _object_id(value):
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, dict):
        return value.get('id')
    return getattr(value, 'id', None)


def _serialized(record):
    serialize = getattr(record, 'serialize', None)
    return serialize() if callable(serialize) else vars(record)


def _custom_fields(record):
    return dict(getattr(record, 'custom_fields', None) or {})


def _snapshot(custom_fields):
    return json.dumps(
        custom_fields,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )


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


def _relationship_value(value, records_by_id, field_name):
    direct = getattr(value, field_name, None)
    if direct is None and isinstance(value, dict):
        direct = value.get(field_name)
    if direct is not None:
        return direct
    record = records_by_id.get(_object_id(value))
    return getattr(record, field_name, None) if record is not None else None


class _NetworkIndex:
    """Read-only NetBox interface, IP, and MAC correlation index."""

    def __init__(self, nb_api):
        self.interfaces = {
            'host': list(nb_api.dcim.interfaces.all()),
            'vm': list(nb_api.virtualization.interfaces.all()),
        }
        self.ips = list(nb_api.ipam.ip_addresses.all())
        self.macs = list(nb_api.dcim.mac_addresses.all())
        self.ips_by_id = {item.id: item for item in self.ips}
        self.macs_by_id = {item.id: item for item in self.macs}

    def for_object(self, kind, record):
        """Return usable addresses assigned to one target object."""

        relation = 'device' if kind == 'host' else 'virtual_machine'
        assigned_type = (
            'dcim.interface'
            if kind == 'host'
            else 'virtualization.vminterface'
        )
        interfaces = [
            item
            for item in self.interfaces[kind]
            if _object_id(_serialized(item).get(relation)) == record.id
        ]
        interface_ids = {item.id for item in interfaces}
        ips = set()
        macs = set()

        primary_ip = _relationship_value(
            _serialized(record).get('primary_ip4'), self.ips_by_id, 'address',
        )
        canonical = _canonical_ip(primary_ip)
        if canonical:
            ips.add(canonical)

        for interface in interfaces:
            primary_mac = _relationship_value(
                _serialized(interface).get('primary_mac_address'),
                self.macs_by_id,
                'mac_address',
            )
            canonical = _canonical_mac(primary_mac)
            if canonical:
                macs.add(canonical)

        for address in self.ips:
            data = _serialized(address)
            if (
                    data.get('assigned_object_type') == assigned_type
                    and _object_id(
                        data.get('assigned_object_id')
                    ) in interface_ids
            ):
                canonical = _canonical_ip(data.get('address'))
                if canonical:
                    ips.add(canonical)

        for address in self.macs:
            data = _serialized(address)
            if (
                    data.get('assigned_object_type') == assigned_type
                    and _object_id(
                        data.get('assigned_object_id')
                    ) in interface_ids
            ):
                canonical = _canonical_mac(data.get('mac_address'))
                if canonical:
                    macs.add(canonical)

        return frozenset(ips), frozenset(macs)


def _discovered_network(kind, discovered):
    ips = set()
    macs = set()
    if kind == 'host':
        candidate = _canonical_ip(discovered.management_ip)
        if candidate:
            ips.add(candidate)
        interfaces = discovered.interfaces
        for interface in interfaces:
            for address in interface.addresses:
                candidate = _canonical_ip(address)
                if candidate:
                    ips.add(candidate)
    else:
        for interface in discovered.interfaces:
            candidate = _canonical_mac(interface.mac_address)
            if candidate:
                macs.add(candidate)
            for address in interface.ip_addresses:
                candidate = _canonical_ip(address)
                if candidate:
                    ips.add(candidate)
    return frozenset(ips), frozenset(macs)


def _contains_v2_identity(record):
    identities = _custom_fields(record).get('sync_identities')
    if identities is None:
        return False
    if not isinstance(identities, list):
        return True
    return any(
        not isinstance(item, dict) or item.get('schema') == 'v2'
        for item in identities
    )


def _matches_identity(record, identity):
    try:
        rank = source_identity_match_rank(_custom_fields(record), identity)
    except ValueError as exc:
        raise EsxiAdoptionError(
            f'Invalid identity metadata on NetBox object id={record.id}'
        ) from exc
    return rank == V2_IDENTITY_MATCH


def _evidence(record, exact_name, matching_ips, matching_macs, conflicts=()):
    signals = []
    if exact_name:
        signals.append('exact_name')
    signals.extend(f'ip:{value}' for value in sorted(matching_ips))
    signals.extend(f'mac:{value}' for value in sorted(matching_macs))
    return AdoptionEvidence(
        object_id=record.id,
        object_name=str(record.name),
        signals=tuple(signals),
        conflicts=tuple(conflicts),
        custom_fields_snapshot=_snapshot(_custom_fields(record)),
    )


def _classify(discovered, kind, identity, all_records, target_records, network):
    managed = [
        record for record in all_records if _matches_identity(record, identity)
    ]
    target_ids = {record.id for record in target_records}
    if managed:
        evidence = tuple(
            _evidence(record, False, (), ()) for record in managed
        )
        if len(managed) == 1 and managed[0].id in target_ids:
            return EsxiAdoptionItem(
                object_kind=kind,
                source_name=discovered.original_name,
                identity=identity,
                classification=AdoptionClassification.MANAGED,
                candidates=evidence,
                selected_object_id=managed[0].id,
            )
        return EsxiAdoptionItem(
            object_kind=kind,
            source_name=discovered.original_name,
            identity=identity,
            classification=AdoptionClassification.AMBIGUOUS,
            candidates=evidence,
        )

    live_ips, live_macs = _discovered_network(kind, discovered)
    candidates = []
    unsafe = False
    for record in target_records:
        record_ips, record_macs = network.for_object(kind, record)
        exact_name = (
            str(record.name).casefold() == discovered.original_name.casefold()
        )
        matching_ips = live_ips & record_ips
        matching_macs = live_macs & record_macs
        if not (exact_name or matching_ips or matching_macs):
            continue

        conflicts = []
        if live_ips and record_ips and not matching_ips:
            conflicts.append('conflicting_ip')
        if live_macs and record_macs and not matching_macs:
            conflicts.append('conflicting_mac')
        if _contains_v2_identity(record):
            conflicts.append('existing_managed_identity')
        evidence = _evidence(
            record, exact_name, matching_ips, matching_macs, conflicts,
        )
        candidates.append(evidence)
        unsafe = unsafe or bool(conflicts)

    if not candidates:
        classification = AdoptionClassification.UNMATCHED
        selected_id = None
    elif len(candidates) == 1 and not unsafe:
        has_network_evidence = any(
            signal.startswith(('ip:', 'mac:'))
            for signal in candidates[0].signals
        )
        classification = (
            AdoptionClassification.SAFE_ADOPTION_CANDIDATE
            if has_network_evidence
            else AdoptionClassification.REVIEW_REQUIRED
        )
        selected_id = candidates[0].object_id
    else:
        classification = AdoptionClassification.AMBIGUOUS
        selected_id = None
    return EsxiAdoptionItem(
        object_kind=kind,
        source_name=discovered.original_name,
        identity=identity,
        classification=classification,
        candidates=tuple(candidates),
        selected_object_id=selected_id,
    )


def _resolve_target(nb_api, config):
    site = nb_api.dcim.sites.get(slug=config.target.site_slug)
    cluster_type = nb_api.virtualization.cluster_types.get(
        slug=config.target.cluster_type_slug
    )
    if site is None or cluster_type is None:
        raise EsxiAdoptionError('ESXi adoption target is incomplete')
    clusters = []
    for cluster in nb_api.virtualization.clusters.filter(
            **cluster_filter(config.target),
    ):
        data = _serialized(cluster)
        if (
                _object_id(data.get('type')) == cluster_type.id
                and data.get('scope_type') == 'dcim.site'
                and data.get('scope_id') == site.id
        ):
            clusters.append(cluster)
    if len(clusters) != 1:
        raise EsxiAdoptionError(
            f'Expected exactly one ESXi adoption target cluster; found {len(clusters)}'
        )
    return site, clusters[0]


def _mark_shared_claims_ambiguous(items):
    claims = {}
    for index, item in enumerate(items):
        for candidate in item.candidates:
            claims.setdefault(
                (item.object_kind, candidate.object_id), []
            ).append(index)
    ambiguous_indexes = {
        index
        for indexes in claims.values()
        if len(set(indexes)) > 1
        for index in indexes
    }
    return tuple(
        replace(
            item,
            classification=AdoptionClassification.AMBIGUOUS,
            selected_object_id=None,
        )
        if index in ambiguous_indexes
        else item
        for index, item in enumerate(items)
    )


def build_esxi_adoption_plan(nb_api, hosts, config):
    """Build an immutable read-only adoption plan for one ESXi source."""

    if config.source_type != 'esxi':
        raise ValueError('ESXi adoption requires source_type=esxi')
    site, cluster = _resolve_target(nb_api, config)
    all_devices = list(nb_api.dcim.devices.all())
    all_vms = list(nb_api.virtualization.virtual_machines.all())
    target_devices = [
        record for record in all_devices
        if (
            _object_id(_serialized(record).get('site')) == site.id
            and _object_id(_serialized(record).get('cluster')) == cluster.id
        )
    ]
    target_vms = [
        record for record in all_vms
        if _object_id(_serialized(record).get('cluster')) == cluster.id
    ]
    network = _NetworkIndex(nb_api)
    items = []
    for host in hosts:
        if (
                host.source != 'esxi'
                or host.source_instance != config.source_instance
        ):
            raise EsxiAdoptionError('Discovered object is outside ESXi source scope')
        items.append(_classify(
            host,
            'host',
            host_source_identity(host),
            all_devices,
            target_devices,
            network,
        ))
        for vm in host.virtual_machines:
            items.append(_classify(
                vm,
                'vm',
                virtual_machine_source_identity(vm),
                all_vms,
                target_vms,
                network,
            ))
    return EsxiAdoptionPlan(
        source_instance=config.source_instance,
        site_id=site.id,
        cluster_id=cluster.id,
        items=_mark_shared_claims_ambiguous(items),
    )


def _target_record(nb_api, plan, item):
    endpoint = (
        nb_api.dcim.devices
        if item.object_kind == 'host'
        else nb_api.virtualization.virtual_machines
    )
    record = endpoint.get(id=item.selected_object_id)
    if record is None:
        raise EsxiAdoptionError('Adoption candidate no longer exists')
    data = _serialized(record)
    in_target = (
        _object_id(data.get('cluster')) == plan.cluster_id
        and (
            item.object_kind == 'vm'
            or _object_id(data.get('site')) == plan.site_id
        )
    )
    if not in_target:
        raise EsxiAdoptionError('Adoption candidate moved outside target')
    return record


def _evidence_is_current(item, evidence, record, network):
    ips, macs = network.for_object(item.object_kind, record)
    for signal in evidence.signals:
        if signal == 'exact_name':
            if str(record.name).casefold() != item.source_name.casefold():
                return False
        elif signal.startswith('ip:'):
            if signal[3:] not in ips:
                return False
        elif signal.startswith('mac:'):
            if signal[4:] not in macs:
                return False
        else:
            return False
    return bool(evidence.signals)


def apply_esxi_adoption_plan(nb_api, plan, *, confirmed=False):
    """Apply only v2 metadata from a previously built, explicitly confirmed plan."""

    if not isinstance(plan, EsxiAdoptionPlan):
        raise TypeError('plan must be EsxiAdoptionPlan')
    if not confirmed:
        raise EsxiAdoptionError('ESXi adoption requires explicit confirmation')
    if any(
            item.classification == AdoptionClassification.AMBIGUOUS
            for item in plan.items
    ):
        raise EsxiAdoptionError('ESXi adoption plan contains ambiguity')

    pending = []
    network = _NetworkIndex(nb_api)
    for item in plan.items:
        if item.classification != AdoptionClassification.SAFE_ADOPTION_CANDIDATE:
            continue
        if (
                item.identity.type != 'esxi'
                or item.identity.instance != plan.source_instance
                or item.identity.kind != item.object_kind
                or len(item.candidates) != 1
                or item.selected_object_id != item.candidates[0].object_id
        ):
            raise EsxiAdoptionError('Invalid ESXi adoption plan item')
        record = _target_record(nb_api, plan, item)
        current = _custom_fields(record)
        evidence = item.candidates[0]
        if _snapshot(current) != evidence.custom_fields_snapshot:
            raise EsxiAdoptionError('Adoption candidate metadata changed after preflight')
        if not _evidence_is_current(item, evidence, record, network):
            raise EsxiAdoptionError('Adoption evidence changed after preflight')
        if _contains_v2_identity(record):
            raise EsxiAdoptionError('Adoption candidate gained a managed identity')
        metadata_base = dict(current)
        if metadata_base.get('sync_identities') is None:
            metadata_base['sync_identities'] = []
        if metadata_base.get('sync_original_names') is None:
            metadata_base['sync_original_names'] = {}
        desired = dict(current)
        desired['sync_identities'] = merge_source_identities(
            metadata_base, item.identity,
        )
        desired['sync_original_names'] = merge_original_name(
            metadata_base, item.identity, item.source_name,
        )
        pending.append((record, desired))

    for record, desired in pending:
        record.update({'custom_fields': desired})
    return len(pending)
