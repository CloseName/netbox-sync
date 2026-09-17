"""Canonical, secret-free synchronization plan contract."""
# pylint: disable=too-many-instance-attributes

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from enum import Enum


PLAN_SCHEMA_VERSION = 1
PLANNER_VERSION = 'web-5a-3'


class SyncAction(str, Enum):
    """Closed set of operator-visible reconciliation outcomes."""

    CREATE = 'CREATE'
    UPDATE = 'UPDATE'
    NO_CHANGE = 'NO_CHANGE'
    REVIEW_REQUIRED = 'REVIEW_REQUIRED'
    BLOCKED = 'BLOCKED'
    IGNORED = 'IGNORED'
    UNSUPPORTED = 'UNSUPPORTED'
    RETAIN_ONLY = 'RETAIN_ONLY'


@dataclass(frozen=True)
class SyncPlanItem:
    """One canonical action and its managed before/after values."""

    object_kind: str
    external_id: str
    name: str
    action: SyncAction
    reason_code: str
    reason: str
    matched_object_id: int | str | None = None
    before: tuple[tuple[str, object], ...] = ()
    after: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class SyncPlan:
    """Immutable exact input to operator review and stale-plan checks."""

    source_instance: str
    source_id: str
    source_type: str
    source_fingerprint: str
    target_fingerprint: str
    provider_fingerprint: str
    netbox_fingerprint: str
    items: tuple[SyncPlanItem, ...]
    schema_version: int = PLAN_SCHEMA_VERSION
    planner_version: str = PLANNER_VERSION

    @property
    def apply_allowed(self):
        """A review item is isolated; an actual blocker stops the whole run."""
        return not any(item.action is SyncAction.BLOCKED for item in self.items)

    def canonical_dict(self):
        """Return a stable primitive mapping suitable for hashing and transport."""
        value = asdict(self)
        value['items'] = sorted(value['items'], key=lambda item: (
            item['object_kind'], item['external_id'], item['action'], item['reason_code']))
        value['apply_allowed'] = self.apply_allowed
        return value

    def canonical_json(self):
        """Serialize deterministically; timestamps and request metadata are absent by design."""
        return json.dumps(self.canonical_dict(), sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True)

    @property
    def digest(self):
        """Bind confirmation to every canonical plan field."""
        return hashlib.sha256(self.canonical_json().encode('utf-8')).hexdigest()


def stable_fingerprint(value):
    """Hash an explicitly safe primitive value."""
    serialized = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def safe_source_fingerprint(config):
    """Fingerprint operational configuration and references without credential values."""
    return stable_fingerprint({
        'id': config.id, 'source_instance': config.source_instance, 'name': config.name,
        'source_type': config.source_type, 'address': config.address,
        'enabled': config.enabled, 'sync_enabled': config.sync_enabled,
        'sync_interval_seconds': config.sync_interval_seconds,
        'verify_ssl': config.verify_ssl, 'legacy_identity_owner': config.legacy_identity_owner,
        'settings': dict(config.settings), 'credential_binding': {
            'username': config.credentials.username,
            'token_id': (config.credentials.token_id.provider, config.credentials.token_id.key),
            'token_secret': (config.credentials.token_secret.provider,
                             config.credentials.token_secret.key),
        },
    })


def target_fingerprint(config):
    """Fingerprint the complete configured NetBox target."""
    return stable_fingerprint(asdict(config.target))


def plan_from_review(review, config):
    """Project the existing provider-neutral preflight into the canonical contract."""
    action_map = {
        'MANAGED': SyncAction.NO_CHANGE,
        'NO_CHANGE': SyncAction.NO_CHANGE,
        'WOULD_CREATE': SyncAction.CREATE,
        'REVIEW_REQUIRED': SyncAction.REVIEW_REQUIRED,
        'CONFLICT': SyncAction.BLOCKED,
        'IGNORED': SyncAction.IGNORED,
        'UNSUPPORTED': SyncAction.UNSUPPORTED,
    }
    items = tuple(SyncPlanItem(
        object_kind=item.object_kind, external_id=item.external_id, name=item.name,
        action=action_map[item.classification.value], reason_code=item.reason_code,
        reason=item.reason, matched_object_id=item.matched_object_id,
        before=(() if item.matched_object_id is None else (
            ('id', item.matched_object_id), ('name', item.matched_object_name))),
        after=(('name', item.name),) if item.future_action in ('create', 'update') else (),
    ) for item in review.items) + (SyncPlanItem(
        object_kind='source', external_id=config.source_instance, name=config.name,
        action=SyncAction.RETAIN_ONLY, reason_code='DISAPPEARANCE_RETAIN_ONLY',
        reason='Managed objects absent from discovery are reported and retained; none are deleted.',
    ),)
    provider = [(item.object_kind, item.external_id, item.name) for item in items]
    netbox = [(item.object_kind, item.matched_object_id, item.before) for item in items
              if item.matched_object_id is not None]
    return SyncPlan(
        source_instance=config.source_instance, source_id=config.id, source_type=config.source_type,
        source_fingerprint=safe_source_fingerprint(config),
        target_fingerprint=target_fingerprint(config),
        provider_fingerprint=stable_fingerprint(sorted(provider)),
        netbox_fingerprint=stable_fingerprint(sorted(netbox, key=repr)), items=items,
    )


def plan_from_mutations(review, config, mutations):
    """Build the exact plan emitted by guarded executors on a recording facade."""
    review_plan = plan_from_review(review, config)
    items = [item for item in review_plan.items
             if item.action in (SyncAction.REVIEW_REQUIRED, SyncAction.BLOCKED,
                                SyncAction.IGNORED, SyncAction.UNSUPPORTED,
                                SyncAction.RETAIN_ONLY)]
    review_endpoints = {'host': 'dcim.devices', 'qemu': 'virtualization.virtual_machines',
                        'lxc': 'virtualization.virtual_machines', 'vm': 'virtualization.virtual_machines'}
    object_names = {(review_endpoints.get(item.object_kind, item.object_kind), item.matched_object_id): item.name
                    for item in review_plan.items if item.matched_object_id is not None}
    object_names.update({(mutation.endpoint, mutation.object_id):
        str(mutation.after.get('name') or mutation.after.get('address') or mutation.after.get('mac_address') or mutation.object_id)
        for mutation in mutations if mutation.operation == 'create'})
    for mutation in mutations:
        fields = {**mutation.before, **mutation.after}
        identities = fields.get('custom_fields', {}).get('sync_identities', []) \
            if isinstance(fields.get('custom_fields'), dict) else []
        identity = next((value for value in identities if isinstance(value, dict)
                         and (value.get('external_id') or value.get('source_id'))), {})
        external_id = identity.get('external_id') or identity.get('source_id') \
            or str(mutation.object_id)
        items.append(SyncPlanItem(
            object_kind=mutation.endpoint, external_id=str(external_id),
            name=str(mutation.after.get('name', object_names.get((mutation.endpoint, mutation.object_id), mutation.object_id))),
            action=SyncAction.CREATE if mutation.operation == 'create' else SyncAction.UPDATE,
            reason_code='GUARDED_EXECUTOR_ACTION',
            reason='Existing guarded executor would perform this managed-field mutation.',
            matched_object_id=None if mutation.operation == 'create' else mutation.object_id,
            before=tuple(sorted(mutation.before.items())), after=tuple(sorted(mutation.after.items())),
        ))
    mutated_ids = {(item.object_kind, item.matched_object_id) for item in items
                   if item.action is SyncAction.UPDATE}
    review_endpoints = {'host': 'dcim.devices', 'qemu': 'virtualization.virtual_machines',
                        'lxc': 'virtualization.virtual_machines',
                        'vm': 'virtualization.virtual_machines'}
    created = {(item.object_kind, item.external_id) for item in items
               if item.action is SyncAction.CREATE}
    # Discovery is evidence, not proof that an executor supports every object.
    # Preserve unexecuted create candidates explicitly instead of silently dropping them.
    items.extend(replace(item, action=SyncAction.UNSUPPORTED,
                         reason_code='EXECUTOR_CREATE_UNSUPPORTED',
                         reason='No supported create operation was produced for this object.',
                         after=())
                 for item in review_plan.items if item.action is SyncAction.CREATE
                 and (review_endpoints.get(item.object_kind), item.external_id) not in created)
    items.extend(item for item in review_plan.items if item.action is SyncAction.NO_CHANGE
                 and (review_endpoints.get(item.object_kind), item.matched_object_id)
                 not in mutated_ids)
    ordered = tuple(sorted(items, key=lambda item: (
        item.object_kind, item.external_id, item.action.value, item.reason_code)))
    return SyncPlan(
        source_instance=review_plan.source_instance, source_id=review_plan.source_id,
        source_type=review_plan.source_type,
        source_fingerprint=review_plan.source_fingerprint,
        target_fingerprint=review_plan.target_fingerprint,
        provider_fingerprint=review_plan.provider_fingerprint,
        netbox_fingerprint=stable_fingerprint([
            (mutation.endpoint, mutation.object_id, mutation.before)
            for mutation in sorted(mutations, key=lambda mutation: (mutation.endpoint, str(mutation.object_id)))]),
        items=ordered,
    )
