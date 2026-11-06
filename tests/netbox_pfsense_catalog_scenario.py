"""Disposable NetBox: catalog migrations, scope, graph, UI, API and retention."""
import runpy
import json
from pathlib import Path
from copy import deepcopy
from uuid import uuid4
from datetime import timedelta
from unittest.mock import patch

runpy.run_path(str(Path(__file__).with_name('netbox_model_scope_scenario.py')))
from django.db import transaction
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import ObjectType
from users.models import ObjectPermission
from virtualization.models import VirtualMachine, VMInterface
from dcim.models import MACAddress
from ipam.models import IPAddress, Prefix
from netbox_guard.models import FirewallObject, FirewallAppliance, FirewallReference, NetworkBinding
from netbox_guard.pfsense_catalog_sync import project, backfill
from netbox_guard.pfsense_catalog import results, document
from netbox_guard.pfsense_inventory import SCHEMA

call_command('makemigrations', 'netbox_guard', check=True, dry_run=True, verbosity=1)
assert 'custom_fields' in ObjectType.objects.get_for_model(FirewallObject).features


def row(component, table, **values):
    return {**{key: [] for key in SCHEMA[component][table]}, 'order': 1, **values}


with transaction.atomic(), override_settings(ALLOWED_HOSTS=['testserver']):
    stamp = timezone.now()
    admin = get_user_model().objects.create(username='firewall-admin-' + uuid4().hex, is_superuser=True)
    user = get_user_model().objects.create(username='firewall-scoped-' + uuid4().hex)
    guest = get_user_model().objects.create(username='firewall-denied-' + uuid4().hex)
    vms = [VirtualMachine.objects.create(name='pfsense-catalog-' + str(n)) for n in range(2)]
    permission = ObjectPermission.objects.create(name='firewall-scope-' + uuid4().hex,
        actions=['view'], constraints={'pk': vms[0].pk})
    permission.object_types.add(ContentType.objects.get_for_model(VirtualMachine))
    permission.users.add(user)
    base = dict(schema='netbox-sync.pfsense.inventory.snapshot.v1', collected_at=stamp.isoformat(), version='2.7.2',
        components=json.loads(Path('/app/tests/fixtures/pfsense_empty_components.json').read_text()),
        packages=dict(collection='ok', items=[]), runtime={k: dict(collection='ok', text='') for k in ('routes4', 'routes6')})
    base['components']['aliases']['tables']['aliases'] = [row('aliases', 'aliases', name=['LAN'], type=['network'], address=['10.160.0.0/16']),
        {**row('aliases', 'aliases', name=['pass'], type=['host'], address=['203.0.113.7']), 'order': 2}]
    base['components']['firewall']['tables']['rules'] = [row('firewall', 'rules', tracker=['1001'], descr=['Allow web'],
        type=['pass'], protocol=['tcp'], **{'destination/address': ['LAN'], 'destination/port': ['443'], 'source/any': ['']})]
    base['components']['nat']['tables']['port_forwards'] = [row('nat', 'port_forwards', descr=['Web NAT'], target=['10.160.0.10'])]
    native_counts = (IPAddress.objects.count(), Prefix.objects.count())
    for vm in vms:
        vm.custom_field_data = {'pfsense_inventory': {**deepcopy(base), 'vm_id': vm.pk}}
        vm.save()
        project(vm)
    assert native_counts == (IPAddress.objects.count(), Prefix.objects.count())
    first = FirewallAppliance.objects.get(vm=vms[0])
    rule = first.entries.get(component='firewall')
    alias = first.entries.get(component='aliases', name='LAN')
    assert FirewallReference.objects.filter(source=rule, target=alias, field='destination/address').exists()
    assert not FirewallReference.objects.filter(source=rule, field='type').exists()
    assert len(list(results(user, {'q': '10.160.0.10'}))) == 3
    assert len(list(results(admin, {'q': '10.160.0.10'}))) == 6
    assert len(list(results(user, {'q': '203.0.113.7'}))) == 1
    assert document(user, rule)['references'][0]['target'] == str(alias.uid)
    ids = set(first.entries.values_list('uid', flat=True))
    project(vms[0])
    assert ids == set(first.entries.values_list('uid', flat=True))
    # Preserve UUID on native rule edits and ordering changes; retain metadata.
    rule.custom_field_data = {'operator_note': 'keep'}
    rule.save()
    vms[0].custom_field_data['pfsense_inventory']['collected_at'] = (stamp + timedelta(seconds=1)).isoformat()
    vms[0].custom_field_data['pfsense_inventory']['components']['firewall']['tables']['rules'][0]['descr'] = ['Changed web']
    vms[0].save()
    project(vms[0])
    rule.refresh_from_db()
    assert rule.name == 'Changed web' and rule.custom_field_data['operator_note'] == 'keep'
    assert rule.uid in ids
    client = Client(); client.force_login(user)
    denied = Client(); denied.force_login(guest)
    for url in (reverse('plugins:netbox_guard:pfsense_overview'), first.get_absolute_url(), rule.get_absolute_url()):
        response = client.get(url)
        assert response.status_code == 200, (url, response.status_code)
        assert vms[1].name not in response.content.decode()
        assert denied.get(url).status_code in (403, 404)
    for tab in ('overview', 'interfaces', 'rules', 'nat', 'aliases', 'routes', 'vpn', 'services', 'observations'):
        response = client.get(first.get_absolute_url(), {'tab': tab})
        assert response.status_code == 200
    private = FirewallAppliance.objects.get(vm=vms[1])
    assert client.get(private.get_absolute_url()).status_code == 404
    assert client.get(private.entries.first().get_absolute_url()).status_code == 404
    with patch('netbox_guard.pfsense_catalog.results', side_effect=AssertionError('Global search must not scan firewall objects')):
        global_html = client.get(reverse('search'), {'q': '10.160.0.10'}).content.decode()
    assert 'pfsense-search-link' not in global_html and 'Web NAT' not in global_html
    assert 'pfsense-search-link' not in denied.get(reverse('search'), {'q': '10.160.0.10'}).content.decode()
    search_url = first.get_absolute_url()
    assert client.get('/plugins/netbox-sync-guard/pfsense/search/').status_code == 404
    search = client.get(search_url, {'q': '10.160.0.10', 'scope': 'firewall'})
    assert search.status_code == 200 and 'alias LAN' in search.content.decode()
    assert client.get(search_url, {'appliance': private.pk, 'q': '10.160.0.10'}).status_code == 200
    api = '/api/plugins/netbox-sync-guard/firewall/catalog/v1/'
    response = client.get(api, {'q': '10.160.0.10'})
    assert response.status_code == 200, response.content[:300]
    assert response.json()['count'] == 3
    assert client.get(api + str(rule.uid) + '/').status_code == 200
    assert client.get(api + str(private.entries.first().uid) + '/').status_code == 404
    assert denied.get(api).status_code == 403
    assert client.post(api, {}).status_code == 405
    from netbox_guard.pfsense_navigation import MENU
    for section in MENU:
        for view in section['children']:
            for sub in view.get('children', [view]):
                response = client.get(first.get_absolute_url(), {'section': section['key'], 'view': view['key'], 'sub': sub['key']})
                assert response.status_code == 200, (section, view, sub, response.status_code)
    overview_html = client.get(reverse('plugins:netbox_guard:pfsense_overview')).content.decode()
    assert '<th>Хост</th>' in overview_html and '<th>Правила</th>' not in overview_html
    assert '>VM в NetBox</a>' in overview_html
    legacy_html = client.get(first.get_absolute_url(), {'section': 'system', 'view': 'users'}).content.decode()
    assert 'Этот раздел ещё не собран' in legacy_html
    # Scoped UI search ignores attempts to inject another firewall or category.
    injected = client.get(search_url, {'q': '10.160.0.10', 'scope': 'firewall', 'appliance': private.pk, 'category': 'system'}).content.decode()
    assert 'Web NAT' in injected and vms[1].name not in injected
    # New System data and explicit parent relationships keep native object URLs.
    system_snapshot = vms[0].custom_field_data['pfsense_inventory']
    for component in ('general', 'users', 'certificates'):
        system_snapshot['components'][component] = dict(presence='built_in', collection='ok', configuration='present', runtime='not_collected',
            tables={table: [] for table in SCHEMA[component]})
    system_snapshot['components']['general']['tables']['settings'] = [row('general', 'settings', hostname=['edge-fw'], domain=['example.test'])]
    system_snapshot['components']['users']['tables']['users'] = [row('users', 'users', uid=['2001'], name=['operator'], cert=['cert1'])]
    system_snapshot['components']['users']['tables']['groups'] = [row('users', 'groups', gid=['2002'], name=['operators'], member=['2001'])]
    system_snapshot['components']['certificates']['tables']['authorities'] = [row('certificates', 'authorities', refid=['ca1'], descr=['Company CA'])]
    system_snapshot['components']['certificates']['tables']['certificates'] = [row('certificates', 'certificates', refid=['cert1'], descr=['Operator certificate'], caref=['ca1'])]
    system_snapshot['components']['ipsec']['tables']['phase1'] = [row('ipsec', 'phase1', ikeid=['1'], descr=['Tunnel'])]
    system_snapshot['components']['ipsec']['tables']['phase2'] = [row('ipsec', 'phase2', ikeid=['1'], uniqid=['p2'], descr=['Protected network'])]
    vms[0].save(); project(vms[0])
    local_user = first.entries.get(component='users', table='users')
    local_cert = first.entries.get(component='certificates', table='certificates')
    assert FirewallReference.objects.filter(source=local_user, target=local_cert, field='cert').exists()
    tunnel = first.entries.get(component='ipsec', table='phase1')
    assert 'Protected network' in client.get(tunnel.get_absolute_url()).content.decode()
    assert 'Operator certificate' in client.get(local_user.get_absolute_url()).content.decode()
    user_html = client.get(first.get_absolute_url(), {'section': 'system', 'view': 'users', 'sub': 'users'}).content.decode()
    assert 'operator' in user_html and 'Web NAT' not in user_html
    settings_html = client.get(first.get_absolute_url(), {'section': 'system', 'view': 'general'}).content.decode()
    assert 'edge-fw' in settings_html and 'example.test' in settings_html
    assert 'Связи и сведения об объекте' in settings_html
    old_uid = local_cert.uid
    system_snapshot['components']['certificates']['tables']['certificates'][0]['descr'] = ['Renewed certificate']
    vms[0].save(); project(vms[0]); local_cert.refresh_from_db()
    assert local_cert.uid == old_uid and local_cert.name == 'Renewed certificate'
    # More than one page must retain every object and all scope filters.
    bulk = deepcopy(vms[0].custom_field_data['pfsense_inventory'])
    bulk['collected_at'] = (stamp + timedelta(seconds=2)).isoformat()
    bulk['components']['firewall']['tables']['rules'] = [
        {**row('firewall', 'rules', tracker=[str(2000 + n)], descr=['Paging rule ' + str(n)]), 'order': n + 1}
        for n in range(61)]
    vms[0].custom_field_data['pfsense_inventory'] = bulk
    vms[0].save(); project(vms[0])
    seen = set()
    for page_number, expected in ((1, 50), (2, 11)):
        payload = client.get(api, {'q': 'Paging rule', 'appliance': first.pk, 'page': page_number}).json()
        assert payload['count'] == 61 and len(payload['results']) == expected
        seen.update(item['id'] for item in payload['results'])
    assert len(seen) == 61
    empty = client.get(api, {'q': 'Paging rule', 'appliance': private.pk}).json()
    assert empty['count'] == 0
    # Import failure rolls back both the snapshot and all derived objects.
    before = set(first.entries.values_list('uid', flat=True))
    try:
        with transaction.atomic():
            vms[0].custom_field_data['pfsense_inventory']['collected_at'] = (stamp + timedelta(seconds=3)).isoformat()
            vms[0].save()
            with patch('netbox_guard.pfsense_catalog_sync.FirewallReference.objects.bulk_create', side_effect=RuntimeError('rollback fixture')):
                project(vms[0])
    except RuntimeError:
        pass
    else:
        raise AssertionError('Expected projection failure')
    vms[0].refresh_from_db()
    assert vms[0].custom_field_data['pfsense_inventory']['collected_at'] == (stamp + timedelta(seconds=2)).isoformat()
    assert before == set(first.entries.values_list('uid', flat=True))
    # Restore the original fixture to verify partial failures against known IDs.
    vms[0].custom_field_data['pfsense_inventory'] = {**deepcopy(base), 'vm_id': vms[0].pk,
        'collected_at': (stamp + timedelta(seconds=3)).isoformat()}
    vms[0].save(); project(vms[0])
    # Successful absence and failed collection are distinct, scoped states.
    vms[0].custom_field_data['pfsense_inventory']['collected_at'] = (stamp + timedelta(seconds=4)).isoformat()
    vms[0].custom_field_data['pfsense_inventory']['components']['firewall'].update(collection='error', configuration='unknown', tables={})
    vms[0].custom_field_data['pfsense_inventory']['components']['nat']['tables']['port_forwards'] = []
    vms[0].save(); project(vms[0])
    rule.refresh_from_db()
    assert rule.state == 'retained'
    assert first.entries.get(component='nat', table='port_forwards').state == 'removed'
    assert private.entries.get(component='firewall').state == 'current'
    # Native interface and prefix links require current same-VM/MAC identity.
    nic = VMInterface.objects.create(virtual_machine=vms[0], name='vtnet0')
    mac = MACAddress.objects.create(mac_address='02:00:00:00:42:01', assigned_object=nic)
    nic.primary_mac_address = mac; nic.save()
    prefix = Prefix.objects.create(prefix='192.0.2.0/24')
    NetworkBinding.objects.create(vm=vms[0], interface_id=nic.pk, interface_key='lan', prefix=prefix)
    snapshot = vms[0].custom_field_data['pfsense_inventory']
    snapshot['collected_at'] = (stamp + timedelta(seconds=5)).isoformat()
    vms[0].custom_field_data['pfsense_network'] = dict(schema='netbox-sync.pfsense.snapshot.v1',
        vm_id=vms[0].pk, collected_at=snapshot['collected_at'], interfaces=[dict(
            configuration=dict(id='lan', name='LAN', device='vtnet0', enabled=True),
            runtime=dict(mac=str(mac.mac_address), addresses=[dict(address='192.0.2.1/24')]),
            match=dict(id=nic.pk, name=nic.name))],
        vlans=[dict(device='vtnet0.42', parent='vtnet0', tag=42, description='Test VLAN')])
    vms[0].save(); project(vms[0])
    interface_object = first.entries.get(component='interfaces', table='interfaces')
    vlan_object = first.entries.get(component='interfaces', table='vlans')
    assert vlan_object.data['tag'] == ['42']
    assert document(admin, vlan_object)['native_interface_id'] is None
    data = document(admin, interface_object)
    assert data['native_interface_id'] == nic.pk and data['prefixes'][0]['id'] == prefix.pk
    vms[0].custom_field_data['pfsense_network']['interfaces'][0]['runtime']['addresses'] = [dict(address='198.51.100.1/24')]
    vms[0].save()
    assert document(admin, interface_object)['prefixes'] == []
    vms[0].custom_field_data['pfsense_network']['interfaces'][0]['runtime']['addresses'] = [dict(address='192.0.2.1/24')]
    vms[0].save()
    nic.primary_mac_address = None; nic.save()
    assert document(admin, interface_object)['native_interface_id'] is None
    assert document(admin, interface_object)['prefixes'] == []
    assert document(user, interface_object)['native_interface_id'] is None
    NetworkBinding.objects.filter(vm=vms[0]).delete(); prefix.delete()
    # Existing snapshots are projected on upgrade without contacting appliances.
    first.delete()
    assert backfill() == 0
    assert FirewallAppliance.objects.filter(vm=vms[0]).exists()
    assert native_counts == (IPAddress.objects.count(), Prefix.objects.count())
    transaction.set_rollback(True)
print('pfSense catalog: native migrations, scoped objects/search/API, graph, stable IDs, retention, backfill and unchanged IPAM OK')
