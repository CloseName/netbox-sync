"""Operator-only provisioning; no credentials printed or existing users repurposed."""
import json
import os
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from users.models import ObjectPermission, Token


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--output', required=True)

    @transaction.atomic
    def handle(self, **options):
        path = Path(options['output'])
        if path.exists(): raise CommandError('Output already exists; no token rotated.')
        user, created = get_user_model().objects.get_or_create(username='netbox-sync-selectel',
            defaults={'last_name': 'Managed Selectel MVP', 'is_active': True})
        if not created and (user.last_name != 'Managed Selectel MVP' or user.is_superuser or user.is_staff):
            raise CommandError('Existing user is not the dedicated Selectel service account.')
        if created:
            user.set_unusable_password(); user.save()
        for codename in ('manage_providerbinding', 'manage_resourceregistry'):
            user.user_permissions.add(Permission.objects.get(content_type__app_label='netbox_guard', codename=codename))
        name = 'Selectel inventory existing device and VM metadata'
        wanted = {ContentType.objects.get(app_label=app, model=model).pk
                  for app, model in (('dcim', 'device'), ('virtualization', 'virtualmachine'))}
        permission, new = ObjectPermission.objects.get_or_create(name=name,
            defaults={'actions': ['view', 'change'], 'constraints': None})
        if not new and (set(permission.actions) != {'view', 'change'} or permission.constraints
                       or set(permission.object_types.values_list('pk', flat=True)) != wanted):
            raise CommandError('Existing permission differs; no overwrite.')
        permission.object_types.set(wanted); permission.users.add(user)
        user = get_user_model().objects.get(pk=user.pk)
        for perm in ('netbox_guard.manage_providerbinding', 'netbox_guard.manage_resourceregistry',
                     'dcim.view_device', 'dcim.change_device', 'virtualization.view_virtualmachine',
                     'virtualization.change_virtualmachine'):
            if not user.has_perm(perm): raise CommandError('Service permission not effective: ' + perm)
        token = Token(user=user, version=2 if settings.API_TOKEN_PEPPERS else 1,
                      description='Selectel MVP isolated importer', write_enabled=True)
        token.full_clean(); token.save()
        secret = token.get_auth_header_prefix().split(' ', 1)[1] + token.token
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'token': secret, 'token_id': token.pk}, stream)
            stream.flush(); os.fsync(stream.fileno())
        self.stdout.write('Dedicated Selectel importer ready; secret written only to protected output file.')
