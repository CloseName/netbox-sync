import json
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from netbox_guard.resource_registry_service import prepare, apply


class Command(BaseCommand):
    help = 'Review/import DNS and storage registry without changing native infrastructure.'

    def add_arguments(self, parser):
        for name in ('input', 'account', 'actor'):
            parser.add_argument('--' + name, required=True)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--fingerprint')
        parser.add_argument('--nonce')
        parser.add_argument('--output')

    def handle(self, **options):
        try:
            path = Path(options['input'])
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError('PROVIDER_REGISTRY_TOO_LARGE')
            doc = json.loads(path.read_bytes())
            if doc.get('account') != options['account']:
                raise ValueError('PROVIDER_ACCOUNT_MISMATCH')
            user = get_user_model().objects.get(username=options['actor'], is_active=True)
            result = (apply(user, options['nonce'], doc, options['fingerprint']) if options['apply']
                      else prepare(user, doc)[3])
            text = json.dumps(result, ensure_ascii=False, indent=2)
            if options['output']:
                with open(options['output'], 'x', encoding='utf-8') as output:
                    output.write(text)
            self.stdout.write(text)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, get_user_model().DoesNotExist) as exc:
            code = str(exc)
            if not code.startswith('PROVIDER_') or not code.replace('_', '').isalnum():
                code = 'PROVIDER_REGISTRY_INPUT_INVALID'
            raise CommandError(code) from None
