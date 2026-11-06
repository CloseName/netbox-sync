"""Disposable NetBox: catalog migrations, scope, graph, UI, API and retention."""
import runpy
import json
from pathlib import Path
from copy import deepcopy
from uuid import uuid4
from datetime import timedelta

runpy.run_path(str(Path(__file__).with_name('netbox_model_scope_scenario.py')))
from django.db import transaction
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from users.models import ObjectPermission
from virtualization.models import VirtualMachine
from ipam.models import IPAddress, Prefix
from netbox_guard.models import FirewallObject, FirewallAppliance, FirewallReference
from netbox_guard.pfsense_catalog_sync import project, backfill
from netbox_guard.pfsense_catalog import results, document
from netbox_guard.pfsense_inventory import SCHEMA

call_command('makemigrations', 'netbox_guard', check=True, dry_run=True, verbosity=1)


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
    base['components']['aliases']['tables']['aliases'] = [row('aliases', 'aliases', name=['LAN'], type=['network'], address=['10.160.0.0/16'])]
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
    alias = first.entries.get(component='aliases')
    assert FirewallReference.objects.filter(source=rule, target=alias, field='destination/address').exists()
    assert len(list(results(user, {'q': '10.160.0.10'}))) == 3
    assert len(list(results(admin, {'q': '10.160.0.10'}))) == 6
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
    for tab in ('overview', 'interfaces', 'rules', 'nat', 'aliases', 'routes', 'vpn', 'services'):
        response = client.get(first.get_absolute_url(), {'tab': tab})
        assert response.status_code == 200
    private = FirewallAppliance.objects.get(vm=vms[1])
    assert client.get(private.get_absolute_url()).status_code == 404
    assert client.get(private.entries.first().get_absolute_url()).status_code == 404
    global_html = client.get(reverse('search'), {'q': '10.160.0.10'}).content.decode()
    assert 'pfsense-search-link' in global_html and 'Web NAT' not in global_html
    search_url = reverse('plugins:netbox_guard:pfsense_search')
    search = client.get(search_url, {'q': '10.160.0.10'})
    assert search.status_code == 200 and 'alias LAN' in search.content.decode()
    assert client.get(search_url, {'appliance': private.pk, 'q': '10.160.0.10'}).status_code == 200
    api = '/api/plugins/netbox-sync-guard/firewall/catalog/v1/'
    response = client.get(api, {'q': '10.160.0.10'})
    assert response.status_code == 200, response.content[:300]
    assert response.json()['count'] == 3
    assert client.get(api + str(rule.uid) + '/').status_code == 200
    assert client.get(api + str(private.entries.first().uid) + '/').status_code == 404
    # Successful absence and failed collection are distinct, scoped states.
    vms[0].custom_field_data['pfsense_inventory']['collected_at'] = (stamp + timedelta(seconds=2)).isoformat()
    vms[0].custom_field_data['pfsense_inventory']['components']['firewall'].update(collection='error', configuration='unknown', tables={})
    vms[0].custom_field_data['pfsense_inventory']['components']['nat']['tables']['port_forwards'] = []
    vms[0].save(); project(vms[0])
    rule.refresh_from_db()
    assert rule.state == 'retained'
    assert first.entries.get(component='nat', table='port_forwards').state == 'removed'
    assert private.entries.get(component='firewall').state == 'current'
    # Existing snapshots are projected on upgrade without contacting appliances.
    first.delete()
    assert backfill() == 0
    assert FirewallAppliance.objects.filter(vm=vms[0]).exists()
    assert native_counts == (IPAddress.objects.count(), Prefix.objects.count())
    transaction.set_rollback(True)
print('pfSense catalog: native migrations, scoped objects/search/API, graph, stable IDs, retention, backfill and unchanged IPAM OK')
