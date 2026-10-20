"""Read-only recovery evidence. Never adopts, mutates, or authorizes an apply."""

import hashlib
import json
from dataclasses import dataclass, field
from typing import NamedTuple
from .source_config import SOURCE_INSTANCE_PATTERN
from .source_identity import SourceIdentity
from .esxi_discovery import _validated_host_hardware_uuid
from .bootstrap_probe import ProbeError


class _RecoveryScope(NamedTuple):
    """Immutable namespace and placement evidence being reviewed."""

    source: str
    anchor: str
    site_id: int
    cluster_id: int
    placement_unavailable: bool


@dataclass
class _RecoveryEvidence:
    """Accumulate evidence without modifying inventory objects."""

    blockers: set = field(default_factory=set)
    owned: list = field(default_factory=list)
    manual: list = field(default_factory=list)
    host_matches: list = field(default_factory=list)
    identity_evidence: list = field(default_factory=list)
    identity_owners: dict = field(default_factory=dict)


class _Ownership(NamedTuple):
    """Partitioned provenance and original parent for one object."""

    current: list
    foreign: list
    parent_id: object


def _parse_identities(row):
    """Validate and deduplicate provenance while retaining legacy evidence."""
    identities = (row.get("custom_fields") or {}).get("sync_identities", [])
    if not isinstance(identities, list):
        raise ProbeError("RESPONSE_INVALID")
    parsed = []
    legacy = False
    for value in identities:
        if not isinstance(value, dict):
            raise ProbeError("RESPONSE_INVALID")
        try:
            identity = SourceIdentity.from_record(value)
        except ValueError:
            raise ProbeError("RESPONSE_INVALID") from None
        if identity is None:
            legacy = True
        else:
            parsed.append(identity)
    # Repeated identical provenance is one fact, not another object.
    parsed = sorted(set(parsed))
    return parsed, legacy


def _owned_placement_matches(scope, kind, row, parent_id):
    """Allow detached owned hosts only for the original unavailable placement."""
    detached_site = row.get("site")
    detached_site = detached_site.get("id") if isinstance(detached_site, dict) else detached_site
    detached_owned_host = (
        scope.placement_unavailable and kind == "device" and parent_id is None and detached_site == scope.site_id
    )
    return parent_id == scope.cluster_id or detached_owned_host


def _assess_owned(scope, evidence, ref, row, ownership):
    """Check owned object identity, placement and host uniqueness evidence."""
    current, foreign, parent_id = ownership
    kind, identifier = ref["kind"], ref["id"]
    evidence.owned.append(ref)
    expected_kind = "host" if kind == "device" else "vm"
    if len(current) != 1 or current[0].kind != expected_kind:
        evidence.blockers.add("OBJECT_IDENTITY_CONFLICT")
    for identity in current:
        owner = evidence.identity_owners.setdefault(identity, (kind, identifier))
        if owner != (kind, identifier):
            evidence.blockers.add("DUPLICATE_OBJECT_IDENTITY")
    if not _owned_placement_matches(scope, kind, row, parent_id):
        evidence.blockers.add("OWNED_OBJECT_OUTSIDE_PLACEMENT")
    if foreign:
        evidence.blockers.add("SHARED_OWNERSHIP")
    if kind == "device":
        hosts = [i for i in current if i.kind == "host"]
        if len(hosts) != 1 or hosts[0].external_id != scope.anchor:
            evidence.blockers.add("HOST_IDENTITY_MISMATCH")
        else:
            evidence.host_matches.append(identifier)


def _assess_row(scope, evidence, kind, row, identifier):
    """Accumulate one validated row without changing its identity or placement."""
    parsed, legacy = _parse_identities(row)
    current = [i for i in parsed if i.type == "esxi" and i.instance == scope.source]
    foreign = [i for i in parsed if i.type != "esxi" or i.instance != scope.source]
    parent = row.get("cluster")
    parent_id = parent.get("id") if isinstance(parent, dict) else parent
    in_target = parent_id == scope.cluster_id
    ref = {"kind": kind, "id": identifier}
    if legacy and (current or in_target):
        evidence.blockers.add("LEGACY_OWNERSHIP_REVIEW_REQUIRED")
    if current or in_target:
        evidence.identity_evidence.append(
            {
                "object": ref,
                "identities": sorted([i.to_record() for i in parsed], key=lambda i: tuple(i.values())),
            }
        )
    if current:
        _assess_owned(scope, evidence, ref, row, _Ownership(current, foreign, parent_id))
    elif in_target:
        if foreign:
            evidence.blockers.add("FOREIGN_SOURCE_IN_PLACEMENT")
        else:
            evidence.manual.append(ref)
    if kind == "device" and any(
        i.kind == "host" and i.type == "esxi" and i.external_id == scope.anchor and i.instance != scope.source
        for i in parsed
    ):
        evidence.blockers.add("HOST_OWNED_BY_OTHER_SOURCE")


def _report(scope, evidence, require_host):
    """Serialize ordered evidence and its original deterministic digest."""
    if len(evidence.host_matches) > 1:
        evidence.blockers.add("DUPLICATE_MANAGED_HOST")
    if require_host and not evidence.host_matches:
        evidence.blockers.add("HISTORICAL_IDENTITY_UNPROVED")
    result = {
        "source_instance": scope.source,
        "host_uuid": scope.anchor,
        "site_id": scope.site_id,
        "cluster_id": scope.cluster_id,
        "owned": sorted(evidence.owned, key=lambda r: (r["kind"], r["id"])),
        "retained_manual": sorted(evidence.manual, key=lambda r: (r["kind"], r["id"])),
        "blockers": sorted(evidence.blockers),
    }
    if scope.placement_unavailable:
        result["placement_requires_review"] = True
        result["placement_status"] = "MISSING_OR_NOT_VISIBLE"
    result["digest"] = hashlib.sha256(
        json.dumps(
            {
                "result": result,
                "identities": sorted(
                    evidence.identity_evidence, key=lambda r: (r["object"]["kind"], r["object"]["id"])
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return result


def _assess_rows(scope, evidence, kind, rows):
    """Validate row IDs independently for each NetBox object type."""
    seen = set()
    for row in rows:
        identifier = row.get("id")
        if type(identifier) is not int or identifier <= 0 or identifier in seen:
            raise ProbeError("RESPONSE_INVALID")
        seen.add(identifier)
        _assess_row(scope, evidence, kind, row, identifier)


def assess(
    source, anchor, site_id, cluster_id, cluster, devices, machines, *, require_host=False, placement_unavailable=False
):
    """Assess a complete bounded inventory fetched by the trusted read worker.

    A restored source keeps its namespace; names and transport addresses play no
    role. This report is evidence for lifecycle confirmation, not a write token.
    """
    if (
        not isinstance(source, str)
        or not SOURCE_INSTANCE_PATTERN.fullmatch(source)
        or not isinstance(anchor, str)
        or _validated_host_hardware_uuid(anchor) != anchor
        or any(type(v) is not int or v <= 0 for v in (site_id, cluster_id))
    ):
        raise ProbeError("RESPONSE_INVALID")
    if len(devices) + len(machines) > 10000:
        raise ProbeError("RESPONSE_INVALID")
    scope = _RecoveryScope(source, anchor, site_id, cluster_id, placement_unavailable)
    evidence = _RecoveryEvidence()
    if not placement_unavailable and (
        cluster.get("id") != cluster_id
        or cluster.get("scope_type") != "dcim.site"
        or cluster.get("scope_id") != site_id
    ):
        evidence.blockers.add("PLACEMENT_CHANGED")
    for kind, rows in (("device", devices), ("vm", machines)):
        _assess_rows(scope, evidence, kind, rows)
    return _report(scope, evidence, require_host)
