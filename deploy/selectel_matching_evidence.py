"""Bounded test-only projection of the installed read-only reconciliation command."""
import json
import re
from collections import Counter


REASONS = frozenset(('existing_binding', 'binding_target_missing', 'stable_identity',
    'identity_needs_confirmation', 'hardware_identity_missing', 'placement_missing',
    'no_existing_candidate', 'hardware_identity_conflict', 'provider_state_not_ready',
    'provider_task_in_progress', 'fresh_inventory_required', 'operator_detached',
    'multiple_provider_resources'))
STATUSES = frozenset(('collected', 'not_collected', 'not_reported', 'conflict',
    'access_denied', 'read_error', 'unsupported_api', 'stale_or_invalid'))
KINDS = frozenset(('system_serial', 'service_tag', 'system_uuid'))


def label(value, allowed):
    return value if isinstance(value, str) and value in allowed else 'unknown'


def name(value):
    return ''.join(c for c in value if c.isprintable())[:200] if isinstance(value, str) else ''


def positive_id(value):
    return value if type(value) is int and value > 0 else None


def rows(value, limit):
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(r, dict) for r in value):
        raise ValueError('Invalid or excessive matching evidence')
    return value


def hardware(document):
    if not isinstance(document, dict):
        raise ValueError('Invalid hardware evidence')
    identifiers = rows(document.get('identifiers', []), 100)
    return dict(status=label(document.get('status'), STATUSES),
                identifier_kinds=sorted({label(r.get('kind'), KINDS) for r in identifiers}),
                identifier_count=len(identifiers))


def candidate(document):
    evidence = document.get('evidence') or {}
    if not isinstance(evidence, dict):
        raise ValueError('Invalid candidate evidence')
    ips, guests = evidence.get('public_ips', []), evidence.get('observed_guest_wans', [])
    if not isinstance(ips, list) or not isinstance(guests, list):
        raise ValueError('Invalid address evidence')
    return dict(resource=label(document.get('resource'), ('device', 'vm')),
                id=positive_id(document.get('id')), name=name(document.get('name')),
                host_device_id=positive_id(document.get('host_device_id')),
                stable_identity=evidence.get('stable_identity') is True,
                hardware_conflict=evidence.get('hardware_conflict') is True,
                same_name=evidence.get('same_name') is True,
                public_ip_match_count=len(ips), guest_wan_match_count=len(guests))


def report(manage, account):
    """Never run a collector or writer; command itself uses a read-only DB transaction."""
    if not re.fullmatch(r'[0-9]{1,20}', account):
        raise ValueError('Invalid account')
    output = manage('provider_hardware_check', '--account', account, '--actor', 'netbox-sync-selectel')
    if len(output.encode('utf-8')) > 8 * 1024 * 1024:
        raise ValueError('Matching evidence exceeds limit')
    # NetBox configuration banners precede the management command's JSON document.
    start = re.search(r'(?m)^\{', output)
    if not start:
        raise ValueError('Matching evidence unavailable')
    document = json.loads(output[start.start():])
    if not isinstance(document, dict) or document.get('account') != account or document.get('writes_performed') is not False:
        raise ValueError('Unexpected matching evidence')
    hosts = [dict(id=positive_id(h.get('id')), name=name(h.get('name')), **hardware(h))
             for h in rows(document.get('hosts'), 5000)]
    pending = [dict(key=name(r.get('key')), name=name(r.get('name')),
                    action=label(r.get('action'), ('blocked', 'bind', 'create', 'detached')),
                    reason=label(r.get('reason'), REASONS), hardware=hardware(r.get('hardware')),
                    candidates=[candidate(c) for c in rows(r.get('candidates'), 5000)])
               for r in rows(document.get('pending_dedicated'), 2000)]
    return dict(account=account, writes_performed=False, scope='stored_inventory_not_fresh_collection',
                pending_dedicated_count=len(pending), decisions=dict(Counter(r['action'] for r in pending)),
                reasons=dict(Counter(r['reason'] for r in pending)), pending_dedicated=pending,
                host_coverage=dict(Counter(h['status'] for h in hosts)), hosts=hosts)
