"""Executed inside disposable PostgreSQL transaction from provider scenario."""
import tempfile
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from netbox_guard.account_import import import_account
from netbox_guard.models import ProviderAccountRun, ProviderInventoryImport, ProviderResourceRegistry
from tools.selectel_audit.resource_registry import registry
document = runpy.run_path(str(Path(__file__).with_name('selectel_inventory_fixture.py')))['fixture']('67890')
document['projects'] = [{'id': 'p', 'name': 'Readable project'}]
payload = dict(account='67890', nonce=str(uuid4()), document=document, registry=registry(document))
before = list(Device.objects.order_by('pk').values())
rejected(lambda: import_account(unprivileged, payload), (DependencyGuardBlocked,))
receipts = ProviderInventoryImport.objects.count()
with patch('netbox_guard.account_import.apply', side_effect=ValueError('registry failed')):
    rejected(lambda: import_account(admin, payload), (ValueError,))
assert ProviderInventoryImport.objects.count() == receipts
assert not ProviderAccountRun.objects.filter(account='67890').exists()
result = import_account(admin, payload)
assert result['servers'] == 2 and result['unmatched'] == 2
assert import_account(admin, payload)['replayed']
assert list(Device.objects.order_by('pk').values()) == before
changed = copy.deepcopy(payload); changed['document']['finished_at'] = '2026-10-13T00:00:00Z'
changed['registry']['observed_at'] = changed['document']['finished_at']
rejected(lambda: import_account(admin, changed), (ValueError,))
assert ProviderAccountRun.objects.filter(account='67890').count() == 1

# Provision a dedicated non-admin account and prove the import works with it.
with tempfile.TemporaryDirectory() as temp:
    output = Path(temp) / 'token.json'
    call_command('configure_selectel_mvp', output=str(output))
    assert json.loads(output.read_text())['token']
    service_user = get_user_model().objects.get(username='netbox-sync-selectel')
    assert not service_user.is_superuser and not service_user.is_staff
    assert not service_user.has_perm('dcim.add_device')
    assert not service_user.has_perm('ipam.change_ipaddress')
    payload['nonce'] = str(uuid4())
    assert import_account(service_user, payload)['servers'] == 2
print('Selectel MVP atomic import, rollback, replay, permissions and native preservation OK')
