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

with override_settings(PLUGINS_CONFIG=config):
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
    from netbox_guard.routing_links import panel as routing_panel
    assert routing_panel(admin, prefix)['networks'][0]['subnets'][0]['gateway_url']
    assert routing_panel(unprivileged, prefix) is None
    review = deletion_review(admin, account, 'delete')
    assert not review['blockers'], review['blockers']
    deletion_execute(admin, account, 'delete', uuid4(), review['fingerprint'])
    assert Tenant.objects.filter(pk=manual.pk).exists()
print('Unified Device layout, every-IP global search, tenancy preservation, routing CIDR search and cleanup OK')
