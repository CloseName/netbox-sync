"""Safe, provider-neutral Web projection of read-only discovery results."""
from ..host_mapping import cluster_filter
# pylint: disable=too-many-instance-attributes

import ipaddress
from dataclasses import dataclass
from enum import Enum

from ..source_identity import (host_source_identity, lxc_source_identity,
                               virtual_machine_source_identity)


class ReviewClassification(str, Enum):
    """Stable public classifications, including future policy outcomes."""

    MANAGED = 'MANAGED'
    REVIEW_REQUIRED = 'REVIEW_REQUIRED'
    WOULD_CREATE = 'WOULD_CREATE'
    IGNORED = 'IGNORED'
    UNSUPPORTED = 'UNSUPPORTED'
    CONFLICT = 'CONFLICT'
    NO_CHANGE = 'NO_CHANGE'


@dataclass(frozen=True)
class ReviewItem:
    """One allowlisted provider object classification."""
    object_kind: str
    name: str
    external_id: str
    classification: ReviewClassification
    reason_code: str
    reason: str
    future_action: str
    matched_object_id: object = None
    matched_object_name: str | None = None


@dataclass(frozen=True)
class DiscoveryReview:
    """Immutable ephemeral result for one registered source."""
    source_instance: str
    source_type: str
    site_slug: str
    cluster_name: str
    items: tuple[ReviewItem, ...]


def _record(value):
    return value.serialize() if hasattr(value, 'serialize') else dict(value)


def _identities(value):
    fields = _record(value).get('custom_fields') or {}
    values = fields.get('sync_identities') if isinstance(fields, dict) else None
    return values if isinstance(values, list) else []


def _object_id(value):
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, dict):
        return value.get('id')
    return getattr(value, 'id', None)


def _ip_value(value):
    if value is None:
        return None
    raw = value.get('address') if isinstance(value, dict) else getattr(value, 'address', value)
    try:
        return str(ipaddress.ip_interface(str(raw)).ip)
    except ValueError:
        return None


def _generic_item(discovered, kind, identity, all_records, target_records):
    managed = [record for record in all_records if identity.to_record() in _identities(record)]
    target_ids = {record.id for record in target_records}
    names = [record for record in target_records
             if str(getattr(record, 'name', _record(record).get('name', ''))).casefold()
             == discovered.original_name.casefold()]
    if len(managed) == 1 and managed[0].id in target_ids:
        record = managed[0]
        return ReviewItem(kind, discovered.original_name, identity.external_id,
                          ReviewClassification.MANAGED, 'IDENTITY_MATCH',
                          'Stable source identity matches an existing NetBox object.', 'none',
                          getattr(record, 'id', None), getattr(record, 'name', None))
    if managed:
        return ReviewItem(kind, discovered.original_name, identity.external_id,
                          ReviewClassification.CONFLICT, 'IDENTITY_SCOPE_CONFLICT',
                          'The stable identity is duplicated or outside the configured target.', 'review')
    if names:
        return ReviewItem(kind, discovered.original_name, identity.external_id,
                          ReviewClassification.REVIEW_REQUIRED, 'NAME_ONLY_CANDIDATE',
                          'A name match exists but names are not identity evidence.', 'review')
    return ReviewItem(kind, discovered.original_name, identity.external_id,
                      ReviewClassification.WOULD_CREATE, 'NO_IDENTITY_MATCH',
                      'No existing object has this stable source identity.', 'create')


def _proxmox_host_item(host, devices, target_devices):
    item = _generic_item(host, 'host', host_source_identity(host), devices, target_devices)
    if item.classification is not ReviewClassification.WOULD_CREATE or not host.management_ip:
        return item
    matches = [record for record in devices
               if _ip_value(getattr(record, 'primary_ip4', None)) == host.management_ip]
    target_ids = {record.id for record in target_devices}
    if not matches:
        return item
    if len(matches) != 1 or matches[0].id not in target_ids:
        return ReviewItem(
            'host', host.original_name, host_source_identity(host).external_id,
            ReviewClassification.CONFLICT, 'MANAGEMENT_IP_CONFLICT',
            'Management IP evidence is ambiguous or outside the configured target.', 'review')
    record = matches[0]
    return ReviewItem(
        'host', host.original_name, host_source_identity(host).external_id,
        ReviewClassification.REVIEW_REQUIRED, 'MANAGEMENT_IP_CANDIDATE',
        'Management IP matches, but network evidence alone does not establish ownership.',
        'review', record.id, getattr(record, 'name', None))


def build_proxmox_review(nb_api, hosts, config):
    """Classify Proxmox inventory without invoking any apply path."""
    site = nb_api.dcim.sites.get(slug=config.target.site_slug)
    cluster_type = nb_api.virtualization.cluster_types.get(slug=config.target.cluster_type_slug)
    if site is None or cluster_type is None:
        raise ValueError('Proxmox review target is incomplete')
    clusters = [cluster for cluster in nb_api.virtualization.clusters.filter(
        **cluster_filter(config.target)) if (
            _object_id(_record(cluster).get('type')) == cluster_type.id
            and _record(cluster).get('scope_type') == 'dcim.site'
            and _record(cluster).get('scope_id') == site.id)]
    if len(clusters) != 1:
        raise ValueError('Proxmox review target cluster is ambiguous')
    cluster = clusters[0]
    devices = tuple(nb_api.dcim.devices.all())
    vms = tuple(nb_api.virtualization.virtual_machines.all())
    target_devices = tuple(record for record in devices if
                           _object_id(_record(record).get('site')) == site.id
                           and _object_id(_record(record).get('cluster')) == cluster.id)
    target_vms = tuple(record for record in vms if
                       _object_id(_record(record).get('cluster')) == cluster.id)
    items = []
    for host in hosts:
        items.append(_proxmox_host_item(host, devices, target_devices))
        items.extend(_generic_item(vm, 'qemu', virtual_machine_source_identity(vm), vms, target_vms)
                     for vm in host.virtual_machines)
        items.extend(_generic_item(lxc, 'lxc', lxc_source_identity(lxc), vms, target_vms)
                     for lxc in host.containers)
    return DiscoveryReview(config.source_instance, config.source_type,
                           config.target.site_slug, config.target.cluster_name, tuple(items))


def build_esxi_review(plan, config):
    """Map the established adoption classifications explicitly."""
    mapping = {
        'MANAGED': (ReviewClassification.MANAGED, 'IDENTITY_MATCH', 'none'),
        'SAFE_ADOPTION_CANDIDATE': (ReviewClassification.REVIEW_REQUIRED,
                                    'SAFE_ADOPTION_CANDIDATE', 'review'),
        'REVIEW_REQUIRED': (ReviewClassification.REVIEW_REQUIRED, 'LEGACY_REVIEW_REQUIRED', 'review'),
        'AMBIGUOUS': (ReviewClassification.CONFLICT, 'AMBIGUOUS_LEGACY_MATCH', 'review'),
        'UNMATCHED': (ReviewClassification.WOULD_CREATE, 'NO_IDENTITY_MATCH', 'create'),
    }
    reasons = {
        'IDENTITY_MATCH': 'Stable source identity matches an existing NetBox object.',
        'SAFE_ADOPTION_CANDIDATE': 'Stable evidence exists, but Web discovery never adopts objects.',
        'LEGACY_REVIEW_REQUIRED': 'Legacy evidence requires operator review and is not adopted.',
        'AMBIGUOUS_LEGACY_MATCH': 'Legacy evidence is ambiguous; processing is blocked.',
        'NO_IDENTITY_MATCH': 'No existing object has this stable source identity.',
    }
    items = []
    for item in plan.items:
        classification, code, action = mapping[item.classification.value]
        candidate = next((value for value in item.candidates
                          if value.object_id == item.selected_object_id), None)
        items.append(ReviewItem(item.object_kind, item.source_name, item.identity.external_id,
                                classification, code, reasons[code], action,
                                item.selected_object_id,
                                None if candidate is None else candidate.object_name))
    return DiscoveryReview(config.source_instance, config.source_type,
                           config.target.site_slug, config.target.cluster_name, tuple(items))
