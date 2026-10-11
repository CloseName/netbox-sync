"""Run via NetBox manage.py shell; add only the optional ESXi event JSON field.

Does not alter existing values, tokens, permissions or Guard records. A conflicting
existing field aborts. Run as the NetBox operator before the first event sync.
"""
from django.db import transaction
from extras.models import CustomField

with transaction.atomic():
    target = CustomField._meta.get_field('object_types').remote_field.model.objects.get(
        app_label='dcim', model='device')
    field = CustomField.objects.select_for_update().filter(name='esxi_events').first()
    if field is not None:
        if (field.type != 'json' or set(field.object_types.values_list('pk', flat=True)) != {target.pk}
                or getattr(field, 'status', 'active') != 'active'
                or field.required or field.unique or field.ui_visible != 'hidden'
                or field.ui_editable != 'no'
                or any(getattr(field, key, None) not in (None, '', {}) for key in (
                    'validation_minimum', 'validation_maximum', 'validation_regex', 'validation_schema'))):
            raise RuntimeError('Existing esxi_events field is incompatible; no changes made')
        print('esxi_events already prepared; existing data preserved')
    else:
        field = CustomField(name='esxi_events', type='json',
                            label='ESXi events for alerting', group_name='NetBox Sync',
                            description='Bounded source events with observed actors; not a complete audit archive.',
                            required=False, unique=False, ui_visible='hidden', ui_editable='no')
        field.full_clean()
        field.save()
        field.object_types.add(target)
        print('esxi_events created for dcim.device; API-only, no Guard changes')
