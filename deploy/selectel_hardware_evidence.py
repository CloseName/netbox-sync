"""Reviewed test diagnostic: inspect stored normalized hardware, never collect/import."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re

FIELDS = {'serial': 'system_serial', 'service_tag': 'service_tag', 'system_uuid': 'system_uuid'}
COMPONENTS = ('cpu', 'ram', 'disk', 'board', 'case', 'gpu', 'pcie', 'misc', 'ocp')
STATUSES = ('collected', 'empty', 'not_reported', 'access_denied', 'unavailable',
            'not_collected', 'partial', 'error')
MARKER = 'SELECTEL_HARDWARE_SHAPE:'


def value_state(data, field, canonical):
    if field not in data:
        return 'missing'
    value = data[field]
    if value is None:
        return 'null'
    if not isinstance(value, str):
        return 'wrong_type'
    if not value.strip():
        return 'empty'
    return 'valid_format' if canonical(FIELDS[field], value) else 'invalid_or_placeholder'


def section_shape(section, canonical):
    """Expose fixed field labels and states only, never values or arbitrary keys."""
    present = isinstance(section, dict)
    section = section if present else {}
    data = section.get('data')
    typ = ('object' if isinstance(data, dict) else 'array' if isinstance(data, list)
           else 'null' if data is None else 'scalar')
    data = data if isinstance(data, dict) else {}
    components = {}
    for kind in COMPONENTS:
        values = data.get(kind)
        if values is None:
            continue
        if not isinstance(values, list) or len(values) > 2000:
            raise ValueError('HARDWARE_COMPONENT_SHAPE_UNSUPPORTED')
        components[kind] = dict(
            present=sum(isinstance(v, dict) and 'serial' in v for v in values),
            nonempty_scalar=sum(isinstance(v, dict) and isinstance(v.get('serial'), str)
                                and bool(v['serial'].strip()) for v in values))
    status = section.get('status')
    return dict(section_present=present, status=status if status in STATUSES else 'unknown',
                retained=bool(section.get('retained')), data_type=typ,
                parser_eligible=status == 'collected' and not section.get('retained') and typ == 'object',
                identity_fields={f: value_state(data, f, canonical) for f in FIELDS},
                provider_hw_uuid_present=bool(data.get('hw_uuid')),
                component_serial_counts=components)


def read_account(account):
    """Runs inside installed test NetBox; DB read-only mode precedes the first query."""
    if not re.fullmatch(r'[0-9]{1,20}', account):
        raise ValueError('INVALID_ACCOUNT')
    from django.contrib.auth import get_user_model
    from django.db import connection, transaction
    from netbox_guard.models import ProviderInventory
    from netbox_guard.provider_reconcile import _permission_all
    from netbox_guard.hardware_identity import canonical

    resources = []
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        user = get_user_model().objects.get(username='netbox-sync-selectel', is_active=True)
        _permission_all(user)
        records = ProviderInventory.objects.filter(account=account, snapshot__identity__kind='dedicated').order_by('provider_key')
        if records.count() > 2000:
            raise ValueError('HARDWARE_REPORT_TOO_LARGE')
        now = datetime.now(timezone.utc)
        for record in records:
            snapshot = record.snapshot
            sections = snapshot.get('sections') or {}
            source = (sections.get('resource') or {}).get('data') or {}
            title = source.get('name') or source.get('user_desc') or ''
            title = ''.join(c for c in title if c.isprintable())[:200] if isinstance(title, str) else ''
            shapes = {n: section_shape(sections.get(n), canonical) for n in ('resource', 'details', 'hardware')}
            eligible = [s for s in shapes.values() if s['parser_eligible']]
            recognized = any('valid_format' in s['identity_fields'].values() for s in eligible)
            category = ('recognized_root_identity' if recognized else 'no_eligible_sections' if not eligible
                        else 'no_recognized_root_identity')
            resources.append(dict(key=record.provider_key, name=title,
                inventory_age_hours=round((now - record.observed_at).total_seconds() / 3600, 1),
                category=category, sections=shapes))
    return dict(account=account, writes_performed=False, scope='stored_normalized_inventory',
                raw_api_fields_not_preserved=True, resource_count=len(resources),
                categories=dict(Counter(r['category'] for r in resources)), resources=resources)


def report(manage, account):
    """Pass this reviewed file as a Python argument; no copying, stdin script or deployment."""
    if not re.fullmatch(r'[0-9]{1,20}', account):
        raise ValueError('INVALID_ACCOUNT')
    program = Path(__file__).read_text(encoding='utf-8')
    program += '\nprint(MARKER + json.dumps(read_account(' + repr(account) + '), ensure_ascii=False))\n'
    output = manage('shell', '-c', program)
    if len(output.encode('utf-8')) > 8 * 1024 * 1024:
        raise ValueError('HARDWARE_REPORT_TOO_LARGE')
    lines = [line[len(MARKER):] for line in output.splitlines() if line.startswith(MARKER)]
    if len(lines) != 1:
        raise ValueError('HARDWARE_REPORT_UNAVAILABLE')
    document = json.loads(lines[0])
    if document.get('account') != account or document.get('writes_performed') is not False:
        raise ValueError('HARDWARE_REPORT_INVALID')
    return document
