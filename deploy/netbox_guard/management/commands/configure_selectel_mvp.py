"""Operator-only provisioning; no credentials printed or existing users repurposed."""
import json
import os
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from users.models import ObjectPermission, Token


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--output', required=True)
        parser.add_argument('--native-resources', action='store_true',
                            help='Grant native reconciliation permissions (test rollout).')
        parser.add_argument('--lifecycle', action='store_true',
                            help='Grant reviewed provider resource deletion (test rollout).')

    @transaction.atomic
    def handle(self, **options):
        path = Path(options['output'])
        if options.get('lifecycle') and not options.get('native_resources'):
            raise CommandError('--lifecycle requires --native-resources.')
        if path.exists(): raise CommandError('Output already exists; no token rotated.')
        user, created = get_user_model().objects.get_or_create(username='netbox-sync-selectel',
            defaults={'last_name': 'Managed Selectel MVP', 'is_active': True})
        if not created and (user.last_name != 'Managed Selectel MVP' or user.is_superuser or getattr(user, 'is_staff', False)):
            raise CommandError('Existing user is not the dedicated Selectel service account.')
        if created:
            user.set_unusable_password(); user.save()
        managed = {ContentType.objects.get(app_label='netbox_guard', model=model).pk
                   for model in ('providerbinding', 'providerresourceregistry')}
        importer, new = ObjectPermission.objects.get_or_create(name='Selectel provider inventory import',
            defaults={'actions': ['manage'], 'constraints': None})
        if not new and (set(importer.actions) != {'manage'} or importer.constraints
                       or not importer.enabled or set(importer.object_types.values_list('pk', flat=True)) != managed):
            raise CommandError('Existing import permission differs; no overwrite.')
        importer.object_types.set(managed); importer.users.add(user)
        name = 'Selectel inventory existing device and VM metadata'
        wanted = {ContentType.objects.get(app_label=app, model=model).pk
                  for app, model in (('dcim', 'device'), ('virtualization', 'virtualmachine'))}
        permission, new = ObjectPermission.objects.get_or_create(name=name,
            defaults={'actions': ['view', 'change'], 'constraints': None})
        if not new and (set(permission.actions) != {'view', 'change'} or permission.constraints or not permission.enabled
                       or set(permission.object_types.values_list('pk', flat=True)) != wanted):
            raise CommandError('Existing permission differs; no overwrite.')
        permission.object_types.set(wanted); permission.users.add(user)
        if options.get('native_resources'):
            wanted_native = {ContentType.objects.get(app_label=app, model=model).pk for app, model in (
                ('dcim', 'device'), ('dcim', 'site'), ('dcim', 'region'), ('dcim', 'devicetype'),
                ('dcim', 'devicerole'), ('dcim', 'manufacturer'), ('virtualization', 'virtualmachine'))}
            native, new = ObjectPermission.objects.get_or_create(name='Selectel native resource reconciliation',
                defaults={'actions': ['view', 'add', 'change'], 'constraints': None})
            if not new and (set(native.actions) != {'view', 'add', 'change'} or native.constraints
                    or not native.enabled or set(native.object_types.values_list('pk', flat=True)) != wanted_native):
                raise CommandError('Existing native reconciliation permission differs; no overwrite.')
            native.object_types.set(wanted_native); native.users.add(user)
            if options.get('lifecycle'):
                deletion, new = ObjectPermission.objects.get_or_create(name='Selectel reviewed native removal',
                    defaults={'actions': ['delete'], 'constraints': None})
                if not new and (set(deletion.actions) != {'delete'} or deletion.constraints or not deletion.enabled
                        or set(deletion.object_types.values_list('pk', flat=True)) != wanted_native):
                    raise CommandError('Existing lifecycle permission differs; no overwrite.')
                deletion.object_types.set(wanted_native); deletion.users.add(user)
                dependency_types = {ContentType.objects.get(app_label=app, model=model).pk for app, model in (
                    ('dcim','interface'), ('virtualization','vminterface'), ('virtualization','cluster'))}
                dependency_view, new = ObjectPermission.objects.get_or_create(name='Selectel lifecycle dependency read only',
                    defaults={'actions':['view'],'constraints':None})
                if not new and (set(dependency_view.actions) != {'view'} or dependency_view.constraints
                        or not dependency_view.enabled or set(dependency_view.object_types.values_list('pk',flat=True)) != dependency_types):
                    raise CommandError('Existing dependency read permission differs; no overwrite.')
                dependency_view.object_types.set(dependency_types); dependency_view.users.add(user)
            ip_types = {ContentType.objects.get(app_label='ipam', model='ipaddress').pk}
            ip_view, new = ObjectPermission.objects.get_or_create(name='Selectel duplicate check IP read only',
                defaults={'actions': ['view'], 'constraints': None})
            if not new and (set(ip_view.actions) != {'view'} or ip_view.constraints or not ip_view.enabled
                    or set(ip_view.object_types.values_list('pk', flat=True)) != ip_types):
                raise CommandError('Existing duplicate check permission differs; no overwrite.')
            ip_view.object_types.set(ip_types); ip_view.users.add(user)
        user = get_user_model().objects.get(pk=user.pk)
        for perm in ('netbox_guard.manage_providerbinding', 'netbox_guard.manage_providerresourceregistry',
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
