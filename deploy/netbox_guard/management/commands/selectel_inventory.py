"""Import an operator-supplied read-only server audit through existing bindings."""
import hashlib
import json
from pathlib import Path
from uuid import UUID
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from netbox_guard.inventory_service import review_inventory, apply_inventory


class Command(BaseCommand):
    help = 'Review or atomically import Selectel servers; native Device/VM creation is disabled.'

    def add_arguments(self, parser):
        parser.add_argument('--input', required=True)
        parser.add_argument('--account', required=True)
        parser.add_argument('--actor', required=True)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--fingerprint')
        parser.add_argument('--nonce')
        parser.add_argument('--output', help='Write the JSON result to a new file (never overwrite).')

    def handle(self, **options):
        try:
            path = Path(options['input'])
            if path.stat().st_size > 256 * 1024 * 1024:
                raise ValueError('SELECTEL_INPUT_TOO_LARGE')
            raw = path.read_bytes()
            document = json.loads(raw)
            if document.get('account') != options['account']:
                raise ValueError('SELECTEL_ACCOUNT_MISMATCH')
            user = get_user_model().objects.get(username=options['actor'], is_active=True)
            evidence = hashlib.sha256(raw).hexdigest()
            if options['apply']:
                if not options['fingerprint'] or not options['nonce']:
                    raise ValueError('SELECTEL_REVIEW_AND_NONCE_REQUIRED')
                result = apply_inventory(user, UUID(options['nonce']), document, evidence, options['fingerprint'])
            else:
                result = review_inventory(user, document, evidence)
            text = json.dumps(result, ensure_ascii=False, indent=2)
            if options['output']:
                with open(options['output'], 'x', encoding='utf-8') as stream:
                    stream.write(text + '\n')
            self.stdout.write(text)
        except (ValueError, OSError, get_user_model().DoesNotExist) as exc:
            # Parser/file errors can embed raw evidence. Only expose stable application codes.
            code = str(exc)
            if not code.startswith(('SELECTEL_', 'PROVIDER_')) or not code.replace('_', '').isalnum():
                code = 'SELECTEL_IMPORT_INPUT_OR_PERMISSION_ERROR'
            raise CommandError(code) from None
