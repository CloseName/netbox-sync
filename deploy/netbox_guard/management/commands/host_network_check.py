"""Permission-filtered, read-only topology inspection; no network calls or writes."""
import json
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from netbox_guard.provider_network_display import document


class Command(BaseCommand):
    help = 'Read stored provider allocations and configured host paths without writes.'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True)
        parser.add_argument('--device', required=True, type=int, action='append')

    def handle(self, **options):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            actor = get_user_model().objects.get(username=options['actor'], is_active=True)
            result = [document(actor, 'device', pk) for pk in sorted(set(options['device']))]
            self.stdout.write(json.dumps({'writes_performed': False, 'devices': result}, ensure_ascii=False, indent=2))
