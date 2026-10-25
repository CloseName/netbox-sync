"""Authenticated evidence lookup; never replay an account import to find its result."""
import re
from uuid import UUID, uuid5
from django.db import connection, transaction
from .service import _permission
from .models import ProviderAccountRun, ProviderInventoryImport, ProviderResourceRegistryChange


@transaction.atomic
def lookup(user, account, nonce):
    actor = _permission(user, 'manage_providerbinding')
    _permission(user, 'manage_resourceregistry')
    if not re.fullmatch(r'[0-9]{1,20}', account):
        raise ValueError('PROVIDER_ACCOUNT_INVALID')
    nonce = UUID(str(nonce))
    result = dict(protocol=1, account=account, run_id=str(nonce))
    # The same account lock as import_account: do not race an in-flight commit.
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))', ['selectel-account:' + account])
        if not cursor.fetchone()[0]:
            return dict(result, outcome='busy')
    receipt = ProviderAccountRun.objects.filter(pk=nonce).first()
    if receipt:
        if receipt.account != account or receipt.actor != actor:
            return dict(result, outcome='conflict')
        return dict(result, outcome='committed', digest=receipt.digest, result=receipt.result)
    stages = any(ProviderInventoryImport.objects.filter(pk=uuid5(nonce, stage)).exists()
                 for stage in ('servers', 'native', 'native-projection'))
    registry = ProviderResourceRegistryChange.objects.filter(pk=uuid5(nonce, 'registry')).exists()
    # No account receipt is NOT proof of no writes in historical versions.
    return dict(result, outcome='partial_evidence' if stages or registry else 'not_found')
