"""Extend an explicitly enabled Selectel lifecycle account without rotating tokens."""
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from users.models import ObjectPermission


class Command(BaseCommand):
    @transaction.atomic
    def handle(self, **options):
        user = get_user_model().objects.filter(username='netbox-sync-selectel').first()
        if user is None:
            self.stdout.write('Selectel cleanup permissions: no importer configured.')
            return
        if user.last_name != 'Managed Selectel MVP' or user.is_superuser or getattr(user, 'is_staff', False):
            raise CommandError('Existing user is not the dedicated Selectel service account.')
        grant = ObjectPermission.objects.filter(name='Selectel reviewed native removal', users=user).first()
        if grant is None:
            self.stdout.write('Selectel cleanup permissions: lifecycle not enabled.')
            return
        native = {ContentType.objects.get(app_label=app, model=model).pk for app, model in (
            ('dcim', 'device'), ('dcim', 'site'), ('dcim', 'region'), ('dcim', 'devicetype'),
            ('dcim', 'devicerole'), ('dcim', 'manufacturer'), ('virtualization', 'virtualmachine'))}
        if (set(grant.actions) != {'delete'} or grant.constraints or not grant.enabled
                or set(grant.object_types.values_list('pk', flat=True)) != native):
            raise CommandError('Existing lifecycle permission differs; no overwrite.')
        wanted = {ContentType.objects.get(app_label='ipam', model=m).pk
                  for m in ('ipaddress', 'prefix', 'vlan', 'vlangroup')}
        permission, new = ObjectPermission.objects.get_or_create(name='Selectel reviewed network removal',
            defaults={'actions': ['view', 'change', 'delete'], 'constraints': None})
        if not new and (set(permission.actions) != {'view', 'change', 'delete'} or permission.constraints
                or not permission.enabled or set(permission.object_types.values_list('pk', flat=True)) != wanted):
            raise CommandError('Existing network removal permission differs; no overwrite.')
        permission.object_types.set(wanted)
        permission.users.add(user)
        self.stdout.write('Selectel account cleanup permissions ready; tokens unchanged.')
