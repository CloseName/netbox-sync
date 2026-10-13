import json
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from netbox_guard.provider_reconcile import prepare, apply


class Command(BaseCommand):
    help = 'Plan or apply identity-based native adoption/creation. No IP assignments or deletions.'

    def add_arguments(self, parser):
        parser.add_argument('--account', required=True)
        parser.add_argument('--actor', required=True)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--fingerprint')
        parser.add_argument('--nonce')
        parser.add_argument('--output')

    def handle(self, **options):
        user = get_user_model().objects.get(username=options['actor'], is_active=True)
        report = (apply(user, options['account'], options['nonce'], options['fingerprint']) if options['apply']
                  else prepare(user, options['account']))
        result = json.dumps(report, ensure_ascii=False, indent=2)
        if options['output']:
            with open(options['output'], 'x', encoding='utf-8') as stream:
                stream.write(result)
        self.stdout.write(result)
