"""Executed within the rollback-only provider scenario, real PostgreSQL/NetBox."""
from ipam.models import IPAddress, Prefix, VLAN, VLANGroup, VRF
from dcim.models import Interface
from virtualization.models import VMInterface
from netbox_guard.models import ProviderIPAMObject, ProviderNetworkLink, ProviderIPAMReceipt
from netbox_guard.selectel_ipam_service import prepare, apply, state
from netbox_guard.provider_network_display import document as network_document
from django.template.loader import render_to_string

snapshot = runpy.run_path(str(Path(__file__).with_name('selectel_ipam_fixture.py')))['snapshot']
host2 = Device.objects.create(name='provider-host2', site=site, device_type=dtype, role=role)
host2_spec = dict(payload, object_id=host2.pk, serial=None, identity=dict(payload['identity'], native_id='server-b'))
apply_binding(admin, uuid4(), host2_spec, review_binding(admin, host2_spec)['fingerprint'])
binding1 = ProviderBinding.objects.get(resource='device', object_id=obj.pk)
binding2 = ProviderBinding.objects.get(resource='device', object_id=host2.pk)
s1, s2 = snapshot(), snapshot('server-b', '8.8.4.6', 'ip-b')
for binding, s in ((binding1, s1), (binding2, s2)):
    ProviderInventory.objects.update_or_create(pk=binding.provider_key, defaults={
        'account': 'fixture', 'snapshot': s, 'evidence_digest': 'd' * 64,
        'observed_at': '2026-10-12T18:00:00Z'})
request = {'account': 'fixture', 'routing_context': 'public-global', 'targets': [
    {'device_id': obj.pk, 'provider_key': binding1.provider_key},
    {'device_id': host2.pk, 'provider_key': binding2.provider_key}]}
nic = Interface.objects.create(device=obj, name='vmk0', type='virtual')
existing1 = IPAddress.objects.create(address='8.8.4.2/29', assigned_object=nic)
guest = VirtualMachine.objects.create(name='firewall', device=host2, site=site)
wan = VMInterface.objects.create(virtual_machine=guest, name='WAN')
existing2 = IPAddress.objects.create(address='8.8.4.6/29', assigned_object=wan)
mgmt = IPAddress.objects.create(address='10.24.0.2/24')
obj.refresh_from_db()
host2.refresh_from_db()
obj.primary_ip4 = existing1
obj.save(update_fields=['primary_ip4', 'last_updated'])
host2.primary_ip4 = mgmt
host2.save(update_fields=['primary_ip4', 'last_updated'])
for baseline in (obj, host2, existing1, existing2):
    baseline.refresh_from_db()
old_hosts = [state(obj), state(host2)]
old_ips = [state(existing1), state(existing2)]
rejected(lambda: prepare(unprivileged, request), (DependencyGuardBlocked,))
preview = prepare(admin, request)
assert sum(o['kind'] == 'prefix' for o in preview['operations']) == 1
assert all(o['action'] == 'adopt' for o in preview['operations'] if o['kind'] == 'ipaddress')
# Ambiguous duplicates and conflicting masks in the SAME routing context stop preview.
with transaction.atomic():
    IPAddress.objects.create(address='8.8.4.2/32')
    rejected(lambda: prepare(admin, request), (ValueError,))
    transaction.set_rollback(True)
# Distinct VRF is not merged with global.
vrf = VRF.objects.create(name='unrelated', rd='65500:9')
foreign = IPAddress.objects.create(address='8.8.4.2/32', vrf=vrf)
assert prepare(admin, request)['fingerprint'] == preview['fingerprint']
# Moving a guest outside the bound host invalidates adoption.
with transaction.atomic():
    VirtualMachine.objects.filter(pk=guest.pk).update(device=obj)
    rejected(lambda: prepare(admin, request), (ValueError,))
    transaction.set_rollback(True)
# Stale review includes IP assignment and host state, even without last_updated.
with transaction.atomic():
    IPAddress.objects.filter(pk=existing2.pk).update(description='intervening')
    rejected(lambda: apply(admin, uuid4(), request, preview['fingerprint']), (ValueError,))
    transaction.set_rollback(True)
# Whole-batch rollback includes native objects and mappings.
counts = (VLAN.objects.count(), Prefix.objects.count(), ProviderIPAMObject.objects.count())
with patch.object(ProviderNetworkLink.objects, 'create', side_effect=ValidationError('fixture')):
    rejected(lambda: apply(admin, uuid4(), request, preview['fingerprint']), (ValidationError,))
assert counts == (VLAN.objects.count(), Prefix.objects.count(), ProviderIPAMObject.objects.count())
nonce = uuid4()
result = apply(admin, nonce, request, preview['fingerprint'])
assert result['writes_performed'] and result['links_created'] == 6
assert apply(admin, nonce, request, preview['fingerprint'])['replayed']
rejected(lambda: apply(admin, nonce, request, '0' * 64), (ValueError,))
for native, before in zip((obj, host2, existing1, existing2), old_hosts + old_ips):
    native.refresh_from_db()
    assert state(native) == before, native
again = prepare(admin, request)
assert again['changes'] == 0
assert not apply(admin, uuid4(), request, again['fingerprint'])['writes_performed']
# SQL protects identities, but permits an ordinary discovery update to non-owned fields.
rejected(lambda: IPAddress.objects.filter(pk=existing1.pk).update(address='8.8.4.3/29'))
rejected(lambda: IPAddress.objects.filter(pk=existing1.pk).delete())
rejected(lambda: IPAddress.objects.create(address='8.8.4.2/32'))
rejected(lambda: Prefix.objects.create(prefix='8.8.4.0/29'))
prefix = Prefix.objects.get(prefix='8.8.4.0/29', vrf=None)
rejected(lambda: Prefix.objects.filter(pk=prefix.pk).update(vlan=None))
rejected(lambda: VLAN.objects.filter(pk=prefix.vlan_id).update(vid=9))
rejected(lambda: ProviderIPAMObject.objects.all().update(claims={}))
rejected(lambda: ProviderNetworkLink.objects.all().delete())
IPAddress.objects.filter(pk=existing1.pk).update(dns_name='ordinary-sync.example')
view = network_document(admin, 'device', host2.pk)
allocation = next(l for l in view['links'] if l['relation'] == 'allocation')
assert allocation['native']['id'] == existing2.pk and allocation['assignment']['id'] == wan.pk
assert 'Selectel' in render_to_string('netbox_guard/provider_networks.html', {'provider_networks': view})
from django.http import Http404
rejected(lambda: network_document(unprivileged, 'device', host2.pk), (Http404,))
# An additional unassigned /32 allocation is added without changing primaries or
# inventing a /24 allocation, VLAN, interface or NAT relation.
s2['sections']['public_ips']['data'].append({'uuid': 'ip-c', 'resource_uuid': 'server-b', 'ip': '8.8.8.8',
    'subnet_uuid': 'subnet-c', 'subnet': '8.8.8.8/32', 'network_uuid': 'unreported', 'netmask': '255.255.255.0'})
s2['sections']['public_subnets']['data'].append({'uuid': 'subnet-c', 'subnet': '8.8.8.8/32', 'network_uuid': 'unreported'})
ProviderInventory.objects.filter(pk=binding2.provider_key).update(snapshot=s2)
more = prepare(admin, request)
apply(admin, uuid4(), request, more['fingerprint'])
created = IPAddress.objects.get(address='8.8.8.8/24', vrf=None)
assert created.assigned_object_id is None and created.nat_inside_id is None
assert Prefix.objects.filter(prefix='8.8.8.8/32').count() == 1
host2.refresh_from_db()
assert host2.primary_ip4_id == mgmt.pk
assert prepare(admin, request)['changes'] == 0
# PostgreSQL inet's /32 display must not make a harmless update fail the guard.
s2['sections']['public_ips']['data'].append({'uuid': 'ip-d', 'resource_uuid': 'server-b', 'ip': '8.8.8.9',
    'subnet_uuid': 'subnet-d', 'subnet': '8.8.8.9/32', 'network_uuid': 'unreported', 'netmask': '255.255.255.255'})
s2['sections']['public_subnets']['data'].append({'uuid': 'subnet-d', 'subnet': '8.8.8.9/32', 'network_uuid': 'unreported'})
ProviderInventory.objects.filter(pk=binding2.provider_key).update(snapshot=s2)
last = prepare(admin, request)
apply(admin, uuid4(), request, last['fingerprint'])
IPAddress.objects.filter(address='8.8.8.9/32', vrf=None).update(description='allowed')
assert prepare(admin, request)['changes'] == 0
print('Native IPAM: scoped adoption, guest assignments, shared prefix, masks, permissions, rollback, replay, SQL guards, HTML and no-op OK')

# Exercise the same command and saved-review path used by the operator script.
import io
import json
import tempfile
work = Path(tempfile.mkdtemp(prefix='guard-ipam-cli-'))
(work / 'request.json').write_text(json.dumps(request), encoding='utf-8')
call_command('selectel_ipam', request=str(work / 'request.json'), actor=admin.username,
             output=str(work / 'review.json'), stdout=io.StringIO())
assert json.loads((work / 'review.json').read_text())['changes'] == 0
bad_request = copy.deepcopy(request)
bad_request['targets'][0]['provider_key'] = 'wrong-resource'
rejected(lambda: prepare(admin, bad_request), (ValueError,))
print('Operator native IPAM command, review export and target pinning OK')
# Provider allocation paths use current assignments and actual VM host placement.
# Neither the read API nor HTML rendering writes native IPAM or provider edges.
with transaction.atomic():
    from netbox_guard.managed_fields import configure_managed_fields
    configure_managed_fields()
    assert CustomField.objects.get(name='proxmox_host_network').ui_visible == 'hidden'
    topology = {'version': 1, 'available': True, 'interfaces': [
        {'name': 'vmbr0', 'type': 'bridge', 'bridge_ports': ['eno1']},
        {'name': 'eno1', 'type': 'eth'}]}
    host2.refresh_from_db()
    host2.custom_field_data.update({'proxmox_host_network': topology,
        'sync_identities': [{'instance': 'test-pve'}]})
    host2.save(update_fields=['custom_field_data'])
    VMInterface.objects.filter(pk=wan.pk).update(custom_field_data={
        'source_bridge': 'vmbr0', 'sync_identities': [{'instance': 'test-pve'}]})
    doc = network_document(admin, 'device', host2.pk)
    row = next(r for r in doc['links'] if r['native']['id'] == existing2.pk and r['relation'] == 'allocation')
    assert row['host_path']['paths'] == [['vmbr0', 'eno1']]
    assert row['host_path']['provider_port_confirmed'] is False
    html = render_to_string('netbox_guard/provider_networks.html', {'provider_networks': doc})
    assert 'eno1' in html
    # Unrelated source bridge metadata cannot be joined to this host.
    VMInterface.objects.filter(pk=wan.pk).update(custom_field_data={
        'source_bridge': 'vmbr0', 'sync_identities': [{'instance': 'other-host'}]})
    row = next(r for r in network_document(admin, 'device', host2.pk)['links'] if r['native']['id'] == existing2.pk and r['relation'] == 'allocation')
    assert 'host_path' not in row
    assert prepare(admin, request)['changes'] == 0
    transaction.set_rollback(True)
print('Configured topology read model, source scoping, HTML and unchanged native IPAM OK')
