"""Explicit supplement to the already authorized native Selectel importer."""
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import CommandError
from users.models import ObjectPermission


def configure(user, delete=False):
    types = {ContentType.objects.get(app_label=app, model=model).pk for app, model in (
        ('dcim', 'interface'), ('tenancy', 'tenant'), ('tenancy', 'tenantgroup'),
        ('ipam', 'vlan'), ('ipam', 'vlangroup'))}
    actions = ['view', 'add', 'change'] + (['delete'] if delete else [])
    name = 'Selectel inventory supplement' + (' lifecycle' if delete else '')
    grant, created = ObjectPermission.objects.get_or_create(name=name, defaults={'actions': actions, 'constraints': None})
    if not created and (set(grant.actions) != set(actions) or grant.constraints or not grant.enabled or
            set(grant.object_types.values_list('pk', flat=True)) != types):
        raise CommandError('Existing Selectel inventory supplement differs; no overwrite.')
    grant.object_types.set(types)
    grant.users.add(user)
