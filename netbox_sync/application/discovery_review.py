"""Safe, provider-neutral Web projection of read-only discovery results."""

from ..host_mapping import cluster_filter, MappingError, PlacementMissing

# pylint: disable=too-many-instance-attributes

import ipaddress
from dataclasses import dataclass, field, replace
from enum import Enum

from ..source_identity import host_source_identity, lxc_source_identity, virtual_machine_source_identity


class ReviewClassification(str, Enum):
    """Stable public classifications, including future policy outcomes."""

    MANAGED = "MANAGED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    WOULD_CREATE = "WOULD_CREATE"
    IGNORED = "IGNORED"
    UNSUPPORTED = "UNSUPPORTED"
    CONFLICT = "CONFLICT"
    NO_CHANGE = "NO_CHANGE"


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
    properties: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveryReview:
    """Immutable ephemeral result for one registered source."""

    source_instance: str
    source_type: str
    site_slug: str
    cluster_name: str
    items: tuple[ReviewItem, ...]


def _record(value):
    return value.serialize() if hasattr(value, "serialize") else dict(value)


def _identities(value):
    fields = _record(value).get("custom_fields") or {}
    values = fields.get("sync_identities") if isinstance(fields, dict) else None
    return values if isinstance(values, list) else []


def _object_id(value):
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, dict):
        return value.get("id")
    return getattr(value, "id", None)


def _ip_value(value):
    if value is None:
        return None
    raw = value.get("address") if isinstance(value, dict) else getattr(value, "address", value)
    try:
        return str(ipaddress.ip_interface(str(raw)).ip)
    except ValueError:
        return None


def _generic_item(discovered, kind, identity, all_records, target_records):
    managed = [record for record in all_records if identity.to_record() in _identities(record)]
    target_ids = {record.id for record in target_records}
    names = [
        record
        for record in target_records
        if str(getattr(record, "name", _record(record).get("name", ""))).casefold()
        == discovered.original_name.casefold()
    ]
    if len(managed) == 1 and managed[0].id in target_ids:
        record = managed[0]
        return ReviewItem(
            kind,
            discovered.original_name,
            identity.external_id,
            ReviewClassification.MANAGED,
            "IDENTITY_MATCH",
            "Stable source identity matches an existing NetBox object.",
            "none",
            getattr(record, "id", None),
            getattr(record, "name", None),
        )
    if managed:
        return ReviewItem(
            kind,
            discovered.original_name,
            identity.external_id,
            ReviewClassification.CONFLICT,
            "IDENTITY_SCOPE_CONFLICT",
            "The stable identity is duplicated or outside the configured target.",
            "review",
        )
    if any(_identities(record) for record in names):
        return ReviewItem(
            kind,
            discovered.original_name,
            identity.external_id,
            ReviewClassification.CONFLICT,
            "OTHER_SOURCE_OWNERSHIP",
            "A matching object retains another source identity. Re-registration does not restore ownership.",
            "review",
        )
    if names:
        return ReviewItem(
            kind,
            discovered.original_name,
            identity.external_id,
            ReviewClassification.REVIEW_REQUIRED,
            "NAME_ONLY_CANDIDATE",
            "A name match exists but names are not identity evidence.",
            "review",
        )
    return ReviewItem(
        kind,
        discovered.original_name,
        identity.external_id,
        ReviewClassification.WOULD_CREATE,
        "NO_IDENTITY_MATCH",
        "No existing object has this stable source identity.",
        "create",
    )


def _provider_host_item(host, devices, target_devices):
    """Project a provider hardware match only without existing source ownership."""
    if not any(host_source_identity(host).to_record() in _identities(record) for record in devices):
        from ..selectel_host_match import matches

        provider = matches(devices, host)
        if provider:
            record = provider[0]
            if record.id not in {r.id for r in target_devices}:
                return ReviewItem(
                    "host",
                    host.original_name,
                    host_source_identity(host).external_id,
                    ReviewClassification.CONFLICT,
                    "SELECTEL_PLACEMENT_REVIEW_REQUIRED",
                    "Select the existing Selectel device site and a compatible cluster before synchronizing.",
                    "review",
                    record.id,
                    getattr(record, "name", None),
                )
            return ReviewItem(
                "host",
                host.original_name,
                host_source_identity(host).external_id,
                ReviewClassification.MANAGED,
                "SELECTEL_HARDWARE_MATCH",
                "Unique hardware identity matches the existing Selectel device. Its provider fields are preserved.",
                "none",
                record.id,
                getattr(record, "name", None),
            )
    return None


def _proxmox_host_item(host, devices, target_devices):
    provider_item = _provider_host_item(host, devices, target_devices)
    if provider_item is not None:
        return provider_item
    item = _generic_item(host, "host", host_source_identity(host), devices, target_devices)
    if item.classification is not ReviewClassification.WOULD_CREATE or not host.management_ip:
        return item
    matches = [record for record in devices if _ip_value(getattr(record, "primary_ip4", None)) == host.management_ip]
    target_ids = {record.id for record in target_devices}
    if not matches:
        return item
    if len(matches) != 1 or matches[0].id not in target_ids:
        return ReviewItem(
            "host",
            host.original_name,
            host_source_identity(host).external_id,
            ReviewClassification.CONFLICT,
            "MANAGEMENT_IP_CONFLICT",
            "Management IP evidence is ambiguous or outside the configured target.",
            "review",
        )
    record = matches[0]
    if _identities(record):
        return ReviewItem(
            "host",
            host.original_name,
            host_source_identity(host).external_id,
            ReviewClassification.CONFLICT,
            "OTHER_SOURCE_OWNERSHIP",
            "A matching object retains another source identity. Re-registration does not restore ownership.",
            "review",
            record.id,
            getattr(record, "name", None),
        )
    return ReviewItem(
        "host",
        host.original_name,
        host_source_identity(host).external_id,
        ReviewClassification.REVIEW_REQUIRED,
        "MANAGEMENT_IP_CANDIDATE",
        "Management IP matches, but network evidence alone does not establish ownership.",
        "review",
        record.id,
        getattr(record, "name", None),
    )


def _review_objects(hosts):
    """Index occurrences without collapsing duplicate provider identities."""
    from collections import defaultdict, deque

    objects = defaultdict(deque)
    for host in hosts:
        objects[("host", host_source_identity(host).external_id, host.original_name)].append(host)
        for vm in host.virtual_machines:
            identity = virtual_machine_source_identity(vm)
            objects[(identity.kind, identity.external_id, vm.original_name)].append(vm)
        for vm in host.containers:
            identity = lxc_source_identity(vm)
            objects[(identity.kind, identity.external_id, vm.original_name)].append(vm)
    return objects


def _inventory_properties(obj, existing):
    """Project only bounded allowlisted inventory facts, preserving previous properties."""
    properties = dict(existing)
    for key in ("vcpus", "memory_bytes"):
        value = getattr(obj, key, None)
        if isinstance(value, int) and value > 0:
            properties[key] = value
    for key in ("status", "architecture", "os_type", "manufacturer", "model", "hypervisor_version"):
        value = getattr(obj, key, None)
        if value:
            properties[key] = str(value)[:200]
    cpu = getattr(obj, "cpu", None)
    if cpu and cpu.model:
        properties["cpu"] = str(cpu.model)[:200]
    interfaces = []
    for nic in obj.interfaces:
        value = {"name": nic.name, "addresses": list(getattr(nic, "ip_addresses", getattr(nic, "addresses", [])))}
        for key in ("mac_address", "bridge", "vlan_id"):
            if getattr(nic, key, None) is not None:
                value[key] = getattr(nic, key)
        interfaces.append(value)
    if interfaces:
        properties["interfaces"] = interfaces
    addresses = sorted({address for nic in interfaces for address in nic["addresses"]})
    if getattr(obj, "management_ip", None):
        addresses = sorted(set(addresses + [obj.management_ip]))
    if addresses:
        properties["addresses"] = addresses
    disks = [
        {"name": getattr(disk, "name", getattr(disk, "path", "")), "size_bytes": disk.size_bytes}
        for disk in obj.disks
        if disk.size_bytes > 0
    ]
    if disks:
        properties["disks"] = disks
    return properties


def _candidate_evidence(item, classification, netbox_url):
    """Build bounded candidate links and identity evidence for review classifications."""
    import json
    from urllib.parse import urlsplit

    base = netbox_url
    parsed = urlsplit(base)
    base = (
        base
        if parsed.scheme in ("https", "http") and parsed.hostname and not parsed.username and not parsed.password
        else ""
    )
    evidence = []
    if classification in (ReviewClassification.CONFLICT, ReviewClassification.REVIEW_REQUIRED):
        for value in sorted(item.candidates, key=lambda c: str(c.object_id)):
            identities = json.loads(value.custom_fields_snapshot).get("sync_identities") or []
            evidence.append(
                {
                    "id": value.object_id,
                    "name": value.object_name,
                    "url": (
                        base
                        + ("/virtualization/virtual-machines/" if item.object_kind == "vm" else "/dcim/devices/")
                        + str(value.object_id)
                        + "/"
                        if base
                        else ""
                    ),
                    "external_ids": sorted(
                        (str(v.get("external_id", v.get("source_id", ""))) for v in identities if isinstance(v, dict))
                    ),
                    "signals": list(value.signals),
                    "conflicts": list(value.conflicts),
                }
            )
    return evidence


def _proxmox_host_review(host, devices, target_devices, vms, target_vms):
    """Classify one host, its network coverage, VMs and containers in order."""
    items = []
    items.append(_proxmox_host_item(host, devices, target_devices))
    missing = ((getattr(host, "proxmox_host_network", None) or {}).get("coverage") or {}).get("missing_references", [])
    if missing:
        names = sorted({r["target"] for r in missing})
        items.append(
            ReviewItem(
                "host_network",
                host.normalized_name,
                host.source_id,
                ReviewClassification.UNSUPPORTED,
                "PROXMOX_NETWORK_REFERENCES_MISSING",
                "Network API omitted referenced interfaces: "
                + ", ".join(names)
                + ". Check configuration and bridge permissions; insufficient permissions are not confirmed.",
                "review",
            )
        )
    items.extend(
        _generic_item(vm, "qemu", virtual_machine_source_identity(vm), vms, target_vms) for vm in host.virtual_machines
    )
    items.extend(_generic_item(lxc, "lxc", lxc_source_identity(lxc), vms, target_vms) for lxc in host.containers)
    return items


def build_proxmox_review(nb_api, hosts, config):
    """Classify Proxmox inventory without invoking any apply path."""
    site = nb_api.dcim.sites.get(slug=config.target.site_slug)
    cluster_type = nb_api.virtualization.cluster_types.get(slug=config.target.cluster_type_slug)
    if site is None or cluster_type is None:
        raise PlacementMissing("Proxmox review target is incomplete")
    clusters = [
        cluster
        for cluster in nb_api.virtualization.clusters.filter(**cluster_filter(config.target))
        if (
            _object_id(_record(cluster).get("type")) == cluster_type.id
            and _record(cluster).get("scope_type") == "dcim.site"
            and _record(cluster).get("scope_id") == site.id
        )
    ]
    if not clusters:
        raise PlacementMissing("Proxmox review target cluster is not visible in scope")
    if len(clusters) != 1:
        raise MappingError("Proxmox review target cluster is ambiguous")
    cluster = clusters[0]
    devices = tuple(nb_api.dcim.devices.all())
    vms = tuple(nb_api.virtualization.virtual_machines.all())
    target_devices = tuple(
        record
        for record in devices
        if _object_id(_record(record).get("site")) == site.id
        and (
            _object_id(_record(record).get("cluster")) == cluster.id
            or (
                _object_id(_record(record).get("cluster")) is None
                and (_record(record).get("custom_fields") or {}).get("selectel_refs")
            )
        )
    )
    target_vms = tuple(record for record in vms if _object_id(_record(record).get("cluster")) == cluster.id)
    items = []
    for host in hosts:
        items.extend(_proxmox_host_review(host, devices, target_devices, vms, target_vms))
    return DiscoveryReview(
        config.source_instance, config.source_type, config.target.site_slug, config.target.cluster_name, tuple(items)
    )


def build_esxi_review(plan, config):
    """Map the established adoption classifications explicitly."""
    mapping = {
        "RETAINED_NAME": (ReviewClassification.REVIEW_REQUIRED, "VM_RECREATED_NAME", "review"),
        "MANAGED": (ReviewClassification.MANAGED, "IDENTITY_MATCH", "none"),
        "SAFE_ADOPTION_CANDIDATE": (ReviewClassification.REVIEW_REQUIRED, "SAFE_ADOPTION_CANDIDATE", "review"),
        "REVIEW_REQUIRED": (ReviewClassification.REVIEW_REQUIRED, "LEGACY_REVIEW_REQUIRED", "review"),
        "AMBIGUOUS": (ReviewClassification.CONFLICT, "AMBIGUOUS_LEGACY_MATCH", "review"),
        "UNMATCHED": (ReviewClassification.WOULD_CREATE, "NO_IDENTITY_MATCH", "create"),
    }
    reasons = {
        "VM_RECREATED_NAME": (
            "The name belongs to a retained VM with a different identity. "
            "Only this VM is skipped; other objects can synchronize. Rename "
            "the new VM and rebuild the plan. Existing bindings are preserved."
        ),
        "IDENTITY_MATCH": "Stable source identity matches an existing NetBox object.",
        "SELECTEL_HARDWARE_MATCH": (
            "Unique hardware identity matches the existing Selectel device. " "Its provider fields are preserved."
        ),
        "SAFE_ADOPTION_CANDIDATE": "Stable evidence exists, but Web discovery never adopts objects.",
        "LEGACY_REVIEW_REQUIRED": "Legacy evidence requires operator review and is not adopted.",
        "AMBIGUOUS_LEGACY_MATCH": "Legacy evidence is ambiguous; processing is blocked.",
        "NO_IDENTITY_MATCH": "No existing object has this stable source identity.",
    }
    items = []
    for item in plan.items:
        classification, code, action = mapping[item.classification.value]
        candidate = next((value for value in item.candidates if value.object_id == item.selected_object_id), None)
        if (
            candidate
            and "selectel_hardware_identity" in candidate.signals
            and classification == ReviewClassification.MANAGED
        ):
            code = "SELECTEL_HARDWARE_MATCH"
        evidence = _candidate_evidence(item, classification, plan.netbox_url)
        items.append(
            ReviewItem(
                item.object_kind,
                item.source_name,
                item.identity.external_id,
                classification,
                code,
                reasons[code],
                action,
                item.selected_object_id,
                None if candidate is None else candidate.object_name,
                properties={"matching_candidates": evidence} if evidence else {},
            )
        )
        if item.object_kind == "host":
            items.append(
                ReviewItem(
                    "host_network",
                    item.source_name,
                    item.identity.external_id,
                    ReviewClassification.UNSUPPORTED,
                    "ESXI_HOST_NETWORK_UNSUPPORTED",
                    (
                        "ESXi topology is stored in a device snapshot. A verified "
                        "connection IPv4 is synchronized separately as a native VMkernel "
                        "interface/IP and device Primary IPv4; other host networking "
                        "remains report-only."
                    ),
                    "none",
                )
            )
    return DiscoveryReview(
        config.source_instance, config.source_type, config.target.site_slug, config.target.cluster_name, tuple(items)
    )


def enrich_review(review, hosts):
    """Attach only allowlisted inventory facts, matching occurrences rather than collapsing IDs.

    Different VMs sharing a stable ID must not inherit each other's network/hardware.
    No descriptions, credentials or arbitrary provider payloads cross this projection.
    """
    objects = _review_objects(hosts)
    items = []
    for item in review.items:
        candidates = objects[(item.object_kind, item.external_id, item.name)]
        if not candidates:
            items.append(item)
            continue
        obj = candidates.popleft()
        properties = _inventory_properties(obj, item.properties)
        items.append(replace(item, properties=properties))
    return replace(review, items=tuple(items))
