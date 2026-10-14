"""Read-only hardware coverage and the resulting reconciliation decision."""
import json
from collections import Counter
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from dcim.models import Device
from netbox_guard.provider_reconcile import prepare
from netbox_guard.hardware_identity import tokens


class Command(BaseCommand):
    help = 'Read-only hardware coverage for a provider account; never applies bindings.'

    def add_arguments(self, parser):
        parser.add_argument('--account', required=True)
        parser.add_argument('--actor', required=True)

    def handle(self, **options):
        user = get_user_model().objects.get(username=options['actor'], is_active=True)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            plan = prepare(user, options['account'])  # Includes full visibility / Guard permission checks.
            hosts = []
            for host in Device.objects.order_by('pk'):
                doc = (host.custom_field_data or {}).get('hardware_identity') or {}
                valid = tokens(doc)
                status = doc.get('status', 'not_collected')
                if status == 'collected' and not valid:
                    status = 'stale_or_invalid'
                hosts.append(dict(id=host.pk, name=host.name, source=doc.get('source'),
                    status=status, observed_at=doc.get('observed_at'),
                    identifiers=[dict(kind=k, value=v) for k, v in sorted(valid)]))
            pending = [dict(key=r['key'], name=r['name'], action=r['action'], reason=r['reason'],
                hardware=r['info']['hardware_identity'], candidates=r['candidates'])
                for r in plan['resources'] if r['resource'] == 'device' and r['action'] != 'unchanged']
            result = dict(account=options['account'], writes_performed=False,
                host_coverage=dict(Counter(h['status'] for h in hosts)), hosts=hosts,
                pending_dedicated=pending,
                decisions=dict(Counter(r['action'] for r in pending)))
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
