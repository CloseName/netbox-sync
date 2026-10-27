"""Native first creation is reviewed per resource, with atomic binding and replay."""
from uuid import uuid4
from netbox_guard.provider_first_creation import review, execute
from netbox_guard.models import ProviderInventoryImport, ProviderDetachedResource

account = '987654321'
ident = dict(account=account, kind='dedicated', native_id=str(uuid4()), project='', region='')
record = ProviderInventory.objects.create(provider_key=provider_key(ident, 'device'), account=account,
    snapshot={'identity': ident, 'sections': {
        'resource': {'status': 'collected', 'data': {'user_desc': 'Reviewed server without serial'}},
        'hardware': {'status': 'collected', 'data': {'service_tag': 'unknown', 'config_name': 'Provider configuration'}},
        'placement': {'status': 'collected', 'data': {'name': 'First creation zone', 'uuid': 'first-zone'}}}},
    evidence_digest='f' * 64, observed_at=timezone.now())
before_ips = list(IPAddress.objects.order_by('pk').values())
before_devices = list(Device.objects.order_by('pk').values())
before_vms = list(VirtualMachine.objects.order_by('pk').values())
preview = review(admin, account, record.pk)
assert preview['eligible'] and preview['writes_performed'] is False
assert list(Device.objects.order_by('pk').values()) == before_devices
assert next(r for r in native_prepare(admin, account)['resources'] if r['key'] == record.pk)['action'] == 'blocked'
native_apply(admin, account, uuid4(), native_prepare(admin, account)['fingerprint'])
assert not ProviderBinding.objects.filter(provider_key=record.pk).exists()
preview = review(admin, account, record.pk)
rejected(lambda: execute(unprivileged, account, record.pk, uuid4(), preview['fingerprint']), (DependencyGuardBlocked, ValueError))
count = Device.objects.count()
receipts = ProviderInventoryImport.objects.count()
proofs = ProviderCreatedObject.objects.count()
site_count = Site.objects.count()
with patch('netbox_guard.provider_creation._add_permission', side_effect=DependencyGuardBlocked('PERMISSION_DENIED')):
    rejected(lambda: execute(admin, account, record.pk, uuid4(), preview['fingerprint']), (DependencyGuardBlocked,))
with patch('netbox_guard.provider_first_creation.apply_binding', side_effect=ValueError('fixture rollback')):
    rejected(lambda: execute(admin, account, record.pk, uuid4(), preview['fingerprint']), (ValueError,))
assert Device.objects.count() == count
assert ProviderInventoryImport.objects.count() == receipts
assert ProviderCreatedObject.objects.count() == proofs
assert Site.objects.count() == site_count
assert not ProviderBinding.objects.filter(provider_key=record.pk).exists()
nonce = uuid4()
created = execute(admin, account, record.pk, nonce, preview['fingerprint'])
assert created['writes_performed'] and not created['replayed']
target = Device.objects.get(pk=created['object_id'])
assert target.serial == '' and target.primary_ip4_id is None and target.primary_ip6_id is None
assert target.site.region_id is None
assert target.custom_field_data['selectel_configuration'] == 'Provider configuration'
assert target.custom_field_data['selectel_inventory']['identity'] == ident
assert ProviderBinding.objects.get(provider_key=record.pk).object_id == target.pk
assert ProviderCreatedObject.objects.filter(account=account, provider_key=record.pk,
    model_label='dcim.device', object_id=target.pk, object_created=target.created).count() == 1
assert execute(admin, account, record.pk, nonce, preview['fingerprint'])['replayed']
assert Device.objects.count() == count + 1
assert not review(admin, account, record.pk)['eligible']
rejected(lambda: execute(admin, account, record.pk, uuid4(), preview['fingerprint']), (ValueError,))
assert native_prepare(admin, account)['resources'][0]['reason'] == 'existing_binding'
assert not native_apply(admin, account, uuid4(), native_prepare(admin, account)['fingerprint'])['writes_performed']
assert list(Device.objects.exclude(pk=target.pk).order_by('pk').values()) == before_devices
assert list(VirtualMachine.objects.order_by('pk').values()) == before_vms
assert list(IPAddress.objects.order_by('pk').values()) == before_ips

# Fresh provider UUID, with no hardware ID, is never a substitute for a candidate review.
other_ident = {**ident, 'native_id': str(uuid4())}
other = ProviderInventory.objects.create(provider_key=provider_key(other_ident, 'device'), account=account,
    snapshot=copy.deepcopy(record.snapshot), evidence_digest='e' * 64, observed_at=timezone.now())
other.snapshot['identity'] = other_ident
other.snapshot['sections']['resource']['data']['user_desc'] = 'Second reviewed server'
other.save()
first_review = review(admin, account, other.pk)
assert first_review['eligible']
# First creation must not rename a shared existing provider Site/Region.
other.snapshot['sections']['placement']['data']['name'] = 'Changed shared placement'
other.save()
changed_placement = review(admin, account, other.pk)
rejected(lambda: execute(admin, account, other.pk, uuid4(), changed_placement['fingerprint']), (ValueError,))
target.site.refresh_from_db()
assert target.site.name.endswith('First creation zone')
assert Device.objects.count() == count + 1
other.snapshot['sections']['placement']['data']['name'] = 'First creation zone'
other.save()
first_review = review(admin, account, other.pk)
collision = Device.objects.create(name='Second reviewed server', site=site, device_type=dtype, role=role)
assert not review(admin, account, other.pk)['eligible']
rejected(lambda: execute(admin, account, other.pk, uuid4(), first_review['fingerprint']), (ValueError,))
collision.delete()
for section, field, value in [('placement', 'retained', True), ('resource', 'retained', True)]:
    other.snapshot['sections'][section][field] = value
    other.save()
    assert not review(admin, account, other.pk)['eligible']
    other.snapshot['sections'][section].pop(field)
other.observed_at = timezone.now() - timedelta(days=3)
other.save()
assert not review(admin, account, other.pk)['eligible']
other.observed_at = timezone.now()
other.save()
assert review(admin, account, other.pk)['eligible']
ProviderDetachedResource.objects.create(account=account, provider_key=other.pk)
assert not review(admin, account, other.pk)['eligible']

# Native forms: GET is read-only; actor/account/key, expiry, checkbox and CSRF gates
# precede the write, and retry of the same submitted form returns the receipt.
import hashlib
import html
import re
from django.core import signing
from django.core.exceptions import PermissionDenied
from netbox_guard.provider_first_creation_views import first_creation, SALT
ProviderDetachedResource.objects.filter(pk=other.pk).delete()
ref = hashlib.sha256(other.pk.encode()).hexdigest()
factory = RequestFactory()
def page(method='get', data=None, user=admin, csrf=False):
    req = getattr(factory, method)('/providers/' + account + '/first-creation/' + ref + '/', data or {})
    req.user = user
    if not csrf:
        req._dont_enforce_csrf_checks = True
    return first_creation(req, account, ref)
count = Device.objects.count()
response = page()
assert response.status_code == 200 and Device.objects.count() == count
token = html.unescape(re.search(r'name="review_token" value="([^"]+)"', response.content.decode()).group(1))
rejected(lambda: page(user=unprivileged), (PermissionDenied,))
assert page('post', {'review_token': token, 'confirm_absent': 'yes'}, csrf=True).status_code == 403
assert page('post', {'review_token': token}).status_code == 409
assert page('post', {'review_token': token + 'changed', 'confirm_absent': 'yes'}).status_code == 409
body = signing.loads(token, salt=SALT)
for field, value in [('actor', str(unprivileged.pk)), ('account', '123'), ('key', record.pk)]:
    wrong = signing.dumps({**body, field: value}, salt=SALT)
    assert page('post', {'review_token': wrong, 'confirm_absent': 'yes'}).status_code == 409
with patch('netbox_guard.provider_first_creation_views.signing.loads', side_effect=signing.SignatureExpired):
    assert page('post', {'review_token': token, 'confirm_absent': 'yes'}).status_code == 409
assert Device.objects.count() == count
for repeat in range(2):
    response = page('post', {'review_token': token, 'confirm_absent': 'yes'})
    assert response.status_code == 200
    assert Device.objects.count() == count + 1
assert list(IPAddress.objects.order_by('pk').values()) == before_ips
print('Reviewed serial-free creation: atomic binding, provenance, replay, candidate/freshness/detach gates and unchanged IPs OK')
