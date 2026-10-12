import json
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from netbox_guard.dependencies import DependencyGuardBlocked
from netbox_guard.selectel_ipam_service import prepare, apply


class Command(BaseCommand):
    help = 'Preview/apply additive native IPAM from accepted dedicated server bindings and stored inventory.'

    def add_arguments(self, parser):
        parser.add_argument('--request', required=True)
        parser.add_argument('--actor', required=True)
        parser.add_argument('--output')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--fingerprint')
        parser.add_argument('--nonce')

    def handle(self, **options):
        try:
            path = Path(options['request'])
            if path.stat().st_size > 32768:
                raise ValueError('SELECTEL_IPAM_REQUEST_TOO_LARGE')
            request = json.loads(path.read_text(encoding='utf-8'))
            user = get_user_model().objects.get(username=options['actor'], is_active=True)
            if options['apply']:
                if not options['fingerprint'] or not options['nonce']:
                    raise ValueError('SELECTEL_IPAM_REVIEW_REQUIRED')
                result = apply(user, options['nonce'], request, options['fingerprint'])
            else:
                result = prepare(user, request)
            text = json.dumps(result, ensure_ascii=False, indent=2)
            if options['output']:
                with open(options['output'], 'x', encoding='utf-8') as stream:
                    stream.write(text + '\n')
            if options['output'] and not options['apply']:
                # Full before/after lives in the review file; terminal remains readable.
                summary = {k: result[k] for k in ('fingerprint', 'changes', 'notes', 'retained_links')}
                summary['objects'] = [{k: op[k] for k in ('kind', 'id', 'action', 'fields', 'refs', 'updates')} for op in result['operations']]
                text = json.dumps(summary, ensure_ascii=False, indent=2)
            self.stdout.write(text)
        except (ValueError, TypeError, KeyError, OSError, DatabaseError, ValidationError,
                DependencyGuardBlocked, get_user_model().DoesNotExist) as exc:
            code = str(exc)
            if not code.startswith('SELECTEL_IPAM_') or not code.replace('_', '').isalnum():
                code = 'SELECTEL_IPAM_INPUT_PERMISSION_OR_DATABASE_REFUSAL'
            raise CommandError(code) from None
