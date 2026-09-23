"""Receipt recovery in a newly restored, fixed-name isolated database."""
import os,sys,json,secrets
from pathlib import Path
assert os.environ.get('NETBOX_SYNC_ISOLATED_MODEL_TEST')=='1'
os.environ.update(DB_HOST='127.0.0.1',DB_USER='postgres',DB_NAME='netbox_sync_guard_restore_test',
    SECRET_KEY=secrets.token_urlsafe(64),DJANGO_SETTINGS_MODULE='netbox.settings')
sys.path.insert(0,'/opt/netbox/netbox')
import django
django.setup()
from django.conf import settings
settings.CACHES={'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache'}}
from django.contrib.auth import get_user_model
from virtualization.models import VirtualMachine,Cluster
from netbox_guard.models import CreationClaim,RetirementReceipt
from netbox_guard.service import retire
row=json.loads(Path('/guard-gate/ready.json').read_text())
user=get_user_model().objects.get(pk=row['actor'])
before=list(CreationClaim.objects.filter(source_instance=row['source']).values_list('resource','object_id'))
assert before and Cluster.objects.filter(pk=row['cluster']).exists()
assert VirtualMachine.objects.filter(pk=row['remaining_vm']).exists()
receipt=retire(user,row['nonce'],row['digest'])
assert str(receipt.pk)==row['nonce'] and receipt.digest==row['digest']
assert list(CreationClaim.objects.filter(source_instance=row['source']).values_list('resource','object_id'))==before
assert RetirementReceipt.objects.filter(intent_id=row['nonce']).count()==1
assert VirtualMachine.objects.filter(pk=row['remaining_vm']).exists()
print('PASS restored guarded receipt retry; claims and remaining owned inventory unchanged')
