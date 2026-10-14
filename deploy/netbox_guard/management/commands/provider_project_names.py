"""Repair only ID-as-name placeholders from the original account audit."""
import copy
import json
from pathlib import Path
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction, connection
from netbox_guard.models import ProviderResourceRegistry, ProviderResourceRegistryChange
from netbox_guard.provider_policy import digest
from netbox_guard.resource_registry_policy import stamp
from netbox_guard.service import _permission


class Command(BaseCommand):
    def add_arguments(self, parser):
        for name in ('input', 'account', 'actor'):
            parser.add_argument('--' + name, required=True)

    @transaction.atomic
    def handle(self, **options):
        user = get_user_model().objects.get(username=options['actor'], is_active=True)
        actor = _permission(user, 'manage_resourceregistry')
        path = Path(options['input'])
        if path.stat().st_size > 128 * 1024 * 1024:
            raise CommandError('Audit too large')
        document = json.loads(path.read_bytes())
        if document.get('schema') != 'selectel-audit-v1' or document.get('account') != options['account']:
            raise CommandError('Account audit required')
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                           ['provider-resource-registry:' + options['account']])
        row = ProviderResourceRegistry.objects.select_for_update().get(pk=options['account'])
        # Metadata must correspond to the exact full snapshot being repaired.
        if stamp(document['finished_at']) != row.observed_at:
            raise CommandError('Use the inventory.json belonging to the imported registry snapshot')
        names = {}
        for project in document.get('projects', []):
            ident, name = project.get('id') or project.get('uuid'), project.get('name')
            if not isinstance(ident, str) or not isinstance(name, str) or not name.strip() or len(name) > 1024:
                continue
            if ident in names and names[ident] != name:
                raise CommandError('Conflicting project names')
            names[ident] = name
        before = copy.deepcopy(row.snapshot)
        count = 0
        for resource in row.snapshot['resources'].values():
            if resource['kind'] == 'project':
                ident = json.loads(resource['key'])[2]
                if resource['name'] == ident and names.get(ident) and names[ident] != ident:
                    resource['name'] = names[ident]
                    count += 1
        if count:
            row.revision += 1
            row.save(update_fields=['snapshot', 'revision'])
            ProviderResourceRegistryChange.objects.create(nonce=uuid4(), registry=row, actor=actor,
                digest=digest(names), revision=row.revision, before=before, after=row.snapshot,
                result={'operation': 'repair_project_names', 'projects_updated': count})
        self.stdout.write(json.dumps({'projects_updated': count, 'writes_performed': bool(count)}))
