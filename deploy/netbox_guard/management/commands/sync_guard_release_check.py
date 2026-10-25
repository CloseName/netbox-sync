"""Machine-readable release check. Never grants permissions or creates resources."""
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.conf import settings
from ...release_manifest import manifest, fingerprint


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--expected', required=True)

    def handle(self, *args, **options):
        import netbox_guard
        actual = fingerprint(manifest(Path(netbox_guard.__file__).parent))
        if actual != options['expected']:
            raise CommandError('GUARD_RELEASE_MISMATCH')
        # Reuse the endpoint's migration/permission contract without a write.
        from ...api.provider import ProviderAccountImport
        from types import SimpleNamespace
        user = get_user_model().objects.filter(username='netbox-sync-selectel').first()
        if user is None or not user.is_active:
            raise CommandError('SELECTEL_IMPORTER_UNAVAILABLE')
        result = ProviderAccountImport().get(SimpleNamespace(user=user)).data
        if result.get('ready') is not True:
            raise CommandError('SELECTEL_IMPORTER_NOT_READY')
        self.stdout.write('GUARD_CHECK:' + json.dumps(dict(
            fingerprint=actual, selectel_protocol=result['selectel_protocol'],
            native_reconcile=settings.PLUGINS_CONFIG.get('netbox_guard', {}).get('selectel_native_reconcile') is True)))
