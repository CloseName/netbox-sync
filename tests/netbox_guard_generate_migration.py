import os, secrets, sys
assert os.environ.get('NETBOX_SYNC_ISOLATED_MODEL_TEST') == '1'
os.environ.update(DB_HOST='127.0.0.1', DB_USER='postgres', DB_NAME='netbox_sync_guard_test',
                  SECRET_KEY=secrets.token_urlsafe(64), DJANGO_SETTINGS_MODULE='netbox.settings')
sys.path.insert(0, '/opt/netbox/netbox')
import django
django.setup()
from django.core.management import call_command
call_command('makemigrations', 'netbox_guard', dry_run=True, check_changes=True, verbosity=3)
