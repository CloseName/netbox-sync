"""Native regression: allocation primary/search/layout, tenancy and routing IPAM."""
from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.test import RequestFactory
from django.template.response import TemplateResponse
from django.urls import resolve
from netbox.search.backends import search_backend
from netbox_guard.provider_components import apply as components_apply
from netbox_guard.provider_tenancy import apply as tenancy_apply
from netbox_guard.routing_projection import apply as routing_apply
from netbox_guard.resource_registry_service import prepare as registry_prepare, apply as registry_apply
from netbox_guard.models import ProviderInventory, ProviderBinding, ProviderCreatedObject
from netbox_guard.card_layout import InventoryLayout, AddressesPanel, HardwarePanel
from netbox_guard.selectel_inventory import projection
from netbox_guard.provider_policy import identity
from netbox_guard.provider_reconcile import prepare as native_prepare, apply as native_apply
from netbox_guard.provider_lifecycle import review as deletion_review, execute as deletion_execute
from tenancy.models import Tenant, TenantGroup
from ipam.models import Prefix, VLAN, VRF
from dcim.views import DeviceView
from types import SimpleNamespace
from tools.selectel_audit.resource_registry import registry as make_registry

@transaction.atomic
def apply_components(*args):
    return components_apply(*args)

with override_settings(PLUGINS_CONFIG=config, ALLOWED_HOSTS=['testserver']):
    unprivileged = get_user_model().objects.create(username='unified-reader-' + uuid4().hex)
    account = '987654330'
    ident = dict(account=account, kind='dedicated', native_id=str(uuid4()), project='project-a', region='')
    def section(value): return dict(status='collected', code='collected', data=value,
                                   observed_at=timezone.now().isoformat(), retained=False)
    snapshot = dict(identity=ident, sections={
        'resource': section(dict(user_desc='Unified allocation fixture', status='ACTIVE')),
        'placement': section(dict(uuid='spb-4', name='SPB-4')),
        'public_ips': section([dict(ip='94.26.228.210'), dict(ip='94.26.228.211'), dict(ip='94.26.228.212')]),
        'hardware': section(dict(cpu=[dict(name='Xeon', count=1)], disk=[dict(name='6 TB HDD', count=2)]))})
    record = ProviderInventory.objects.create(provider_key=identity(ident, 'device'), account=account,
        snapshot=snapshot, evidence_digest='b'*64, observed_at=timezone.now())
    from netbox_guard.provider_first_creation import review as creation_review, execute as creation_execute
    plan = creation_review(admin, account, record.pk)
    creation_execute(admin, account, record.pk, uuid4(), plan['fingerprint'])
    binding = ProviderBinding.objects.get(provider_key=record.pk)
    device = Device.objects.get(pk=binding.object_id)
    result = apply_components(admin, binding, device, snapshot)
    device.refresh_from_db()
    assert str(device.primary_ip4.address.ip) == '94.26.228.210', result
    assert device.interfaces.get(name='Selectel allocations').ip_addresses.count() == 3
    assert device.tenant.group.name == 'Аккаунт ' + account
    initial = (IPAddress.objects.count(), Tenant.objects.count(), TenantGroup.objects.count())
    assert not apply_components(admin, binding, device, snapshot)['primary_updated']
    assert initial == (IPAddress.objects.count(), Tenant.objects.count(), TenantGroup.objects.count())
    search_backend.cache(device)
    for address in ('94.26.228.210', '94.26.228.211', '94.26.228.212'):
        assert any(hit.object == device for hit in search_backend.search(address, user=admin)), address
    original_layout = DeviceView.layout
    request = RequestFactory().get(device.get_absolute_url())
    request.user = admin
    request.resolver_match = resolve(device.get_absolute_url())
    response = TemplateResponse(request, 'dcim/device.html', {'object': device, 'layout': original_layout})
    InventoryLayout(lambda r: None).process_template_response(request, response)
    panels = response.context_data['layout'].rows[0].columns[1].panels
    assert panels[0].__class__.__name__ == 'DeviceManagementPanel'
    assert isinstance(panels[1], AddressesPanel) and isinstance(panels[2], HardwarePanel)
    assert not any(isinstance(p, AddressesPanel) for p in original_layout.rows[0].columns[1].panels)
    rendered = panels[1].get_context({'object': device, 'request': request})
    assert len(rendered['provider_addresses']) == 3
    assert sum(r['primary'] for r in rendered['provider_addresses']) == 1
    assert '94.26.228.212' in panels[1].render({'object': device, 'request': request})
    assert 'Xeon' in panels[2].render({'object': device, 'request': request})
    from django.test import Client
    client = Client()
    client.force_login(admin)
    page = client.get(device.get_absolute_url())
    assert page.status_code == 200
    html = page.content.decode()
    assert '94.26.228.212' in html and 'Xeon' in html
    assert html.index('Management') < html.index('94.26.228.212') < html.index('Xeon')
    assert not any(isinstance(p, AddressesPanel) for p in DeviceView.layout.rows[0].columns[1].panels)
    reader = Client()
    reader.force_login(unprivileged)
    denied = reader.get(device.get_absolute_url())
    assert denied.status_code in (403, 404) and b'94.26.228.212' not in denied.content
    # Standalone host facts must render without any Selectel allocation snapshot.
    standalone = Device.objects.create(name='Standalone host fixture', site=device.site,
        role=device.role, device_type=device.device_type, status='active',
        custom_field_data=dict(cpu_model='Standalone host CPU', memory_mb=32768))
    standalone_html = client.get(standalone.get_absolute_url()).content.decode()
    assert 'Standalone host CPU' in standalone_html and '32 ГиБ' in standalone_html
    assert 'data-sync-hardware' in standalone_html
    standalone.delete()
    manual = Tenant.objects.create(name='Keep manual', slug='keep-manual-unified')
    device.tenant = manual
    device.save(update_fields=['tenant'])
    apply_components(admin, binding, device, snapshot)
    device.refresh_from_db()
    assert device.tenant_id == manual.pk

    # Fresh provider location evidence must not move an existing Device.
    from netbox_guard.inventory_service import review_inventory, apply_inventory
    from dcim.models import Site
    original_site, site_count = device.site_id, Site.objects.count()
    update_document = dict(schema='selectel-audit-v1', account_verified=True, account=account,
        finished_at=timezone.now().isoformat(), datasets=[
            dict(service='dedicated', kind='resources', status='collected', project='', region='',
                 items=[dict(uuid=ident['native_id'], service_type='server', project_uuid='project-a', user_desc=device.name,
                             location_uuid='different-location')]),
            dict(service='dedicated', kind='locations', status='collected', project='', region='',
                 items=[dict(uuid='different-location', name='Different Site')])])
    preview = review_inventory(admin, update_document, 'c'*64)
    assert preview['server_count'] == 1 and preview['bound_count'] == 1, preview
    apply_inventory(admin, uuid4(), update_document, 'c'*64, preview['fingerprint'])
    device.refresh_from_db()
    assert device.site_id == original_site and Site.objects.count() == site_count

    timestamp = timezone.now().isoformat()
    document = make_registry(dict(account=account, finished_at=timestamp,
        datasets=[dict(service='global-router', kind=kind, status='collected', items=items) for kind, items in (
            ('routers', [dict(id='router-one', name='Routing unified')]),
            ('networks', [dict(id='network-one', name='LAN unified', router_id='router-one', vlan=1368, zone_name='SPB-4')]),
            ('subnets', [dict(id='subnet-one', name='LAN management', network_id='network-one', cidr='10.78.12.0/26',
                             gateway='10.78.12.1', service_addresses=['10.78.12.61', '10.78.12.62'])]),
            ('static_routes', [dict(id='route-one', name='PAM-DEV-CLOUD', router_id='router-one', cidr='10.160.0.0/16', next_hop='10.78.12.2')]))],
        coverage=[dict(service='global-router', kind='routers', status='collected')]))
    preview = registry_prepare(admin, document)[3]
    registry_apply(admin, uuid4(), document, preview['fingerprint'])
    with transaction.atomic(): assert not routing_apply(admin, account)
    prefix = Prefix.objects.get(prefix='10.78.12.0/26', description='LAN management')
    assert prefix.vlan.vid == 1368
    assert IPAddress.objects.filter(vrf=prefix.vrf, address__net_host='10.78.12.1').exists()
    assert not Prefix.objects.filter(vrf=prefix.vrf, prefix='10.160.0.0/16').exists()
    counts = (Prefix.objects.count(), VLAN.objects.count(), IPAddress.objects.count(), VRF.objects.count())
    with transaction.atomic(): assert not routing_apply(admin, account)
    assert counts == (Prefix.objects.count(), VLAN.objects.count(), IPAddress.objects.count(), VRF.objects.count())
    search_backend.cache(prefix)
    assert any(hit.object == prefix for hit in search_backend.search('10.78.12.42', user=admin))
    assert any(hit.object == prefix.vrf for hit in search_backend.search('10.160.0.42', user=admin))
    assert prefix.vrf.tenant.name == 'Глобальный роутинг'
    # Upgrade an old owned routing tenant without moving any native IPAM object.
    from netbox_guard.provider_tenancy import resolve as resolve_tenant
    old_tenant = resolve_tenant(admin, dict(account=account, project=''))
    old_tenant.name = 'Без проекта / уровень аккаунта'
    old_tenant.save(update_fields=['name'])
    collision = Tenant.objects.create(name='Общие ресурсы аккаунта', slug='manual-general-unified', group=old_tenant.group)
    vrf = prefix.vrf
    vrf.tenant = old_tenant
    vrf.save(update_fields=['tenant'])
    proof = ProviderCreatedObject.objects.get(model_label='ipam.vrf', object_id=vrf.pk)
    proof.projection_values['tenant_id'] = old_tenant.pk
    proof.save(update_fields=['projection_values'])
    with transaction.atomic(): assert not routing_apply(admin, account)
    vrf.refresh_from_db()
    assert vrf.tenant.name == 'Глобальный роутинг'
    assert prefix.vrf_id == vrf.pk
    old_tenant.refresh_from_db()
    assert old_tenant.name == 'Без проекта / уровень аккаунта'
    collision.delete()
    with transaction.atomic(): assert not routing_apply(admin, account)
    old_tenant.refresh_from_db()
    assert old_tenant.name == 'Общие ресурсы аккаунта'
    from netbox_guard.routing_catalog import routes as find_routes
    from django.urls import reverse
    matches = find_routes(admin, '10.160.0.42')
    match = next(r for r in matches if r['account'] == account)
    assert match['name'] == 'PAM-DEV-CLOUD' and match['next_hop'] == '10.78.12.2'
    search_page = client.get(reverse('search'), {'q': '10.160.0.0/16'})
    assert search_page.status_code == 200
    assert 'routing-search-results' in search_page.content.decode()
    assert 'PAM-DEV-CLOUD' in search_page.content.decode()
    route_page = client.get(match['href'])
    assert route_page.status_code == 200
    route_html = route_page.content.decode()
    assert all(value in route_html for value in ('PAM-DEV-CLOUD', '10.160.0.0/16', '10.78.12.2', 'Routing unified'))
    # Both router entry points use tabs; VLAN keeps native prefixes without a duplicate panel.
    for router_url in (match['router_url'], vrf.get_absolute_url()):
        separator = '&' if '?' in router_url else '?'
        networks_html = client.get(router_url).content.decode()
        assert 'data-routing-network' in networks_html and 'Сети и подсети' in networks_html
        routes_response = client.get(router_url + separator + 'routing_tab=routes')
        assert routes_response.status_code == 200
        routes_html = routes_response.content.decode()
        assert 'PAM-DEV-CLOUD' in routes_html and 'data-routing-network' not in routes_html
        assert 'routing_tab=networks' in routes_html
    vlan_page = client.get(prefix.vlan.get_absolute_url())
    assert vlan_page.status_code == 200 and '10.78.12.0/26' in vlan_page.content.decode()
    assert 'Маршрутизация Selectel' not in vlan_page.content.decode()
    prefix_page = client.get(prefix.get_absolute_url())
    assert prefix_page.status_code == 200 and '10.78.12.61' in prefix_page.content.decode()
    query_page = client.get(match['router_url'] + '&q=10.160.0.0%2F16')
    assert query_page.status_code == 200 and 'PAM-DEV-CLOUD' in query_page.content.decode()
    assert 'data-routing-network' not in query_page.content.decode()
    overview = client.get(reverse('plugins:netbox_guard:routing_overview'), {'account': account})
    assert overview.status_code == 200 and 'Routing unified' in overview.content.decode()
    assert find_routes(unprivileged, '10.160.0.0/16') == []
    assert reader.get(reverse('plugins:netbox_guard:routing_overview')).status_code == 403
    assert b'PAM-DEV-CLOUD' not in reader.get(reverse('search'), {'q': '10.160.0.0/16'}).content
    # A manual VRF tenant change is not overwritten by a later projection.
    vrf.tenant = manual
    vrf.save(update_fields=['tenant'])
    with transaction.atomic(): assert 'routing_manual_edit_preserved' in routing_apply(admin, account)
    vrf.refresh_from_db()
    assert vrf.tenant_id == manual.pk
    vrf.tenant_id = proof.projection_values['tenant_id'] = resolve_tenant(admin, dict(account=account), routing=True).pk
    vrf.save(update_fields=['tenant'])
    from netbox_guard.routing_links import panel as routing_panel
    assert routing_panel(admin, prefix)['networks'][0]['subnets'][0]['gateway_url']
    assert routing_panel(unprivileged, prefix) is None
    review = deletion_review(admin, account, 'delete')
    assert not review['blockers'], review['blockers']
    deletion_execute(admin, account, 'delete', uuid4(), review['fingerprint'])
    assert Tenant.objects.filter(pk=manual.pk).exists()
print('Unified Device layout, every-IP global search, tenancy preservation, routing CIDR search and cleanup OK')
