"""Validate saved plan candidates, never replay an apply or a CREATE request."""
import json
import sys
import time
from types import SimpleNamespace
from uuid import UUID
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from netbox_guard.api.views import validated_create_values
from netbox_guard.dependencies import DependencyGuardBlocked
from netbox_guard.models import CreationReceipt

MAX_BYTES = 8 * 1024 * 1024


def diagnose(envelope, actor):
    if envelope.get('format') != 'sync-guard-candidates-v1':
        raise ValueError('CANDIDATE_FORMAT_INVALID')
    from netbox_guard.service import _source
    source = _source(envelope['source_instance'])
    run = str(UUID(envelope['run_id']))
    candidates = envelope['candidates']
    if not isinstance(candidates, list) or len(candidates)>10000:
        raise ValueError('CANDIDATE_FORMAT_INVALID')
    report = {'evidence':'SAVED_PLAN_NOT_ORIGINAL_REQUEST', 'run_id':run,
              'source_instance':source, 'actor_id':actor.pk, 'candidates':[], 'writes':False}
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
            cursor.execute("SET LOCAL statement_timeout = '10000ms'")
        if not actor.is_active or not actor.has_perm('netbox_guard.create_creationreceipt'):
            raise ValueError('ACTOR_NOT_AUTHORIZED')
        receipts = CreationReceipt.objects.filter(source_instance=source)
        if receipts.count()>10000: raise ValueError('RECEIPT_LIMIT_EXCEEDED')
        report['existing_receipts'] = list(receipts.order_by('nonce').values('resource','object_id','nonce'))
        request = SimpleNamespace(user=actor)
        deadline = time.monotonic()+120
        for index, candidate in enumerate(candidates):
            if time.monotonic()>deadline: raise ValueError('DIAGNOSIS_DEADLINE')
            data = candidate['data']
            if not isinstance(data,dict) or any(k in data for k in ('id','pk','tags')):
                raise ValueError('CANDIDATE_FORMAT_INVALID')
            row = {'index':index, 'external_id':candidate['external_id']}
            # Never substitute temporary references or infer the newly created host.
            if any(type(data.get(k)) is int and data[k]<=0 for k in ('cluster','device','site','platform','role','tenant')):
                row.update(code='UNRESOLVED_PLAN_REFERENCE', validation_issues=[])
            else:
                try:
                    validated_create_values('vm', data, request)
                    row.update(code='SERIALIZER_VALID', validation_issues=[])
                except DependencyGuardBlocked as exc:
                    row.update(code=str(exc), validation_issues=getattr(exc,'validation_issues',[]))
            report['candidates'].append(row)
    return report


class Command(BaseCommand):
    help = 'Read candidate envelope from stdin; validate only, never save/create or POST.'

    def add_arguments(self, parser):
        parser.add_argument('--actor-id', type=int, required=True)

    def handle(self, *args, **options):
        try:
            raw = sys.stdin.buffer.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES: raise ValueError('CANDIDATE_TOO_LARGE')
            actor = get_user_model().objects.get(pk=options['actor_id'])
            result = diagnose(json.loads(raw), actor)
        except Exception:
            # Do not print DB/serializer exception messages or candidate content.
            raise CommandError('DIAGNOSIS_FAILED: check actor, input format and read-only database access') from None
        self.stdout.write(json.dumps(result, sort_keys=True, default=str))
