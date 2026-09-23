"""Run inside the pinned disposable NetBox image, never against an external DB."""
import os
import secrets
import sys
import faulthandler
faulthandler.dump_traceback_later(300, exit=True)
assert os.environ.get('NETBOX_SYNC_ISOLATED_MODEL_TEST') == '1'
os.environ.update(DB_HOST='127.0.0.1', DB_USER='postgres', DB_NAME='netbox_sync_model_scope_test',
                  SECRET_KEY=secrets.token_urlsafe(64), DJANGO_SETTINGS_MODULE='netbox.settings')
sys.path.insert(0, '/opt/netbox/netbox')
import psycopg
with psycopg.connect('host=127.0.0.1 user=postgres dbname=postgres', autocommit=True) as connection:
    exists = connection.execute("SELECT 1 FROM pg_database WHERE datname='netbox_sync_model_scope_test'").fetchone()
    if not exists:
        connection.execute('CREATE DATABASE netbox_sync_model_scope_test')
import django
django.setup()
from django.conf import settings
settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
from django.core.management import call_command
call_command('migrate', verbosity=0, interactive=False)
from django.db import transaction
from django.core.exceptions import ValidationError
from ipam.models import VRF, IPAddress
with transaction.atomic():
    first = VRF.objects.create(name='isolated-a', enforce_unique=True)
    second = VRF.objects.create(name='isolated-b', enforce_unique=True)
    a = IPAddress(address='192.0.2.60/24', vrf=first)
    a.full_clean(); a.save()
    b = IPAddress(address='192.0.2.60/24', vrf=second)
    b.full_clean(); b.save()
    for mask in (24, 32):
        rejected = IPAddress(address=f'192.0.2.60/{mask}', vrf=first)
        try: rejected.full_clean()
        except ValidationError: pass
        else: raise AssertionError('Same host address in enforced VRF accepted')
    assert IPAddress.objects.filter(pk__in=[a.pk, b.pk]).count() == 2
    transaction.set_rollback(True)
print('NetBox 4.7 actual model: distinct VRFs accepted; same-VRF equal/different masks refused; transaction rolled back')
