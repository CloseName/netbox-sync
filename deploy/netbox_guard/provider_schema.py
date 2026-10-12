"""Versioned, idempotent provider projection schema. No inventory writes."""
from django.db import transaction
from extras.models import CustomField

FIELDS = {'selectel_refs': ('json', 'hidden'), 'selectel_summary': ('text', 'if-set')}
SCOPES = {('dcim', 'device'), ('virtualization', 'virtualmachine')}


def check_schema(using='default'):
    for name, (kind, visible) in FIELDS.items():
        field = CustomField.objects.using(using).filter(name=name).first()
        if field is None or (field.type != kind or field.group_name != 'Selectel'
                or field.required or field.unique or field.ui_editable != 'no'
                or field.ui_visible != visible
                or {(t.app_label, t.model) for t in field.object_types.all()} != SCOPES):
            raise ValueError('PROVIDER_SCHEMA_INCOMPATIBLE')


def configure_provider_fields(using='default'):
    with transaction.atomic(using=using):
        _configure(using)


def _configure(using):
    for name, (kind, visible) in FIELDS.items():
        field = CustomField.objects.using(using).select_for_update().filter(name=name).first()
        if field is None:
            field = CustomField(name=name, label='Selectel' if kind == 'text' else 'Selectel bindings',
                                type=kind, group_name='Selectel', required=False, unique=False,
                                ui_visible=visible, ui_editable='no')
            field.full_clean()
            field.save(using=using)
            for app, model in sorted(SCOPES):
                field.object_types.add(field.object_types.model.objects.using(using).get(app_label=app, model=model))
    check_schema(using)
