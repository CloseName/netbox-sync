"""Native manual association: preservation, stale reviews, rollback and replay."""
from netbox_guard.provider_manual_link import review as link_review, execute as link_execute
from netbox_guard.provider_manual_link_views import manual_link, SALT as LINK_SALT
from django.core import signing
import hashlib

account = '98765'
manual_record = insert_resource('dedicated', 'manual-link-fixture', 'Provider label without candidate')
manual_target = Device.objects.create(name='Existing private host', site=site, device_type=dtype, role=role)
manual_preview = link_review(admin, account, manual_record.pk, manual_target.pk)
manual_ref = hashlib.sha256(manual_record.pk.encode()).hexdigest()
def manual_page(method='GET', data=None, user=admin):
    request = getattr(RequestFactory(), method.lower())('/providers/link/', data or {})
    request.user = user
    request._dont_enforce_csrf_checks = True
    return manual_link(request, account, manual_ref)
assert manual_page(data={'q': 'Existing private host'}).status_code == 200
assert manual_page(data={'object_id': manual_target.pk}).status_code == 200
wrong_actor_token = signing.dumps(dict(actor='not-admin', account=account, key=manual_record.pk,
    object_id=manual_target.pk, nonce=str(uuid4()), fingerprint=manual_preview['fingerprint']), salt=LINK_SALT)
assert manual_page('POST', {'review_token': wrong_actor_token, 'confirm_same': 'yes'}).status_code == 409
assert not ProviderBinding.objects.filter(provider_key=manual_record.pk).exists()
rejected(lambda: link_review(unprivileged, account, manual_record.pk, manual_target.pk), (DependencyGuardBlocked, ValueError))
manual_target.name = 'Renamed private host'
manual_target.save()
rejected(lambda: link_execute(admin, account, manual_record.pk, manual_target.pk, uuid4(), manual_preview['fingerprint']), (ValueError,))
manual_preview = link_review(admin, account, manual_record.pk, manual_target.pk)
with patch('netbox_guard.provider_manual_link.apply_binding', side_effect=ValueError('rollback fixture')):
    rejected(lambda: link_execute(admin, account, manual_record.pk, manual_target.pk, uuid4(), manual_preview['fingerprint']), (ValueError,))
assert not ProviderBinding.objects.filter(provider_key=manual_record.pk).exists()
manual_nonce = uuid4()
manual_result = link_execute(admin, account, manual_record.pk, manual_target.pk, manual_nonce, manual_preview['fingerprint'])
assert manual_result['object_id'] == manual_target.pk
assert link_execute(admin, account, manual_record.pk, manual_target.pk, manual_nonce, manual_preview['fingerprint'])['replayed']
manual_target.refresh_from_db()
assert manual_target.name == 'Renamed private host' and manual_target.serial == ''
assert manual_target.primary_ip4_id is None and manual_target.site_id == site.pk
assert not ProviderCreatedObject.objects.filter(model_label='dcim.device', object_id=manual_target.pk).exists()
assert next(p for p in native_prepare(admin, account)['resources'] if p['key'] == manual_record.pk)['reason'] == 'existing_binding'
other_manual_record = insert_resource('dedicated', 'manual-link-conflict', 'Another provider label')
rejected(lambda: link_review(admin, account, other_manual_record.pk, manual_target.pk), (ValueError,))
manual_vm = insert_resource('cloud_vm', 'manual-link-stale', 'Stale provider VM', age=3)
rejected(lambda: link_review(admin, account, manual_vm.pk, cloud_vm.pk), (ValueError,))
print('Manual association preserves native object ownership; stale, permission, conflict, rollback and replay checks OK')
