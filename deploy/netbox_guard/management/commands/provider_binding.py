"""Trusted operator entry point; preview first, explicit fingerprint for apply."""
import json
from pathlib import Path
from uuid import UUID
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError
from netbox_guard.dependencies import DependencyGuardBlocked
from netbox_guard.provider_service import review_binding, apply_binding


class Command(BaseCommand):
    help = 'Review or accept a Selectel binding; never infer identity from IP/name.'

    def add_arguments(self, parser):
        parser.add_argument('--request', required=True, help='JSON spec without credentials')
        parser.add_argument('--actor', required=True, help='Existing NetBox username with binding and target permissions')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--fingerprint')
        parser.add_argument('--nonce', type=UUID)

    def handle(self, *args, **options):
        try:
            path = Path(options['request'])
            if path.stat().st_size > 32768:
                raise ValueError('Oversized request')
            spec = json.loads(path.read_text(encoding='utf-8'))
            user = get_user_model().objects.get(username=options['actor'])
            if options['apply']:
                if not options['fingerprint'] or not options['nonce']:
                    raise ValueError('Review fingerprint and nonce required')
                result = apply_binding(user, options['nonce'], spec, options['fingerprint'])
            else:
                result = review_binding(user, spec)
        except (ValueError, TypeError, KeyError, OSError, IntegrityError, ValidationError,
                DependencyGuardBlocked, get_user_model().DoesNotExist):
            raise CommandError('PROVIDER_REQUEST_REFUSED: check schema, permissions, identity and review freshness') from None
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
