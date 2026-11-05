"""Native ports, disks, primary IP and repeated removal/reconnection, isolated DB."""
from django.db import transaction
from django.utils import timezone
from netbox_guard.provider_reconcile import prepare as native_prepare, apply as native_apply
from netbox_guard.provider_policy import identity as provider_key
from netbox_guard.models import ProviderInventory
from netbox_guard.provider_components import apply as apply_components

@transaction.atomic
def project_components(*args):
    return apply_components(*args)

def rejected(action, errors):
    try:
        action()
    except errors:
        return
    raise AssertionError('Expected component refusal')
from netbox_guard.provider_lifecycle import review as lifecycle_review, execute as lifecycle_execute
from virtualization.models import VirtualDisk
from ipam.models import VRF

with override_settings(PLUGINS_CONFIG=config):
    component_account = '987654322'
    def new_cloud(account=component_account, floating=True):
        ident = dict(account=account, kind='cloud_vm', native_id=str(uuid4()), project='p', region='ru-9')
        def section(data): return dict(status='collected', data=data)
        snapshot = dict(identity=ident, sections={
            'resource': section(dict(name='Regional cloud '+ident['native_id'][:8], status='SHELVED_OFFLOADED')),
            'placement': dict(status='not_reported', data={}),
            'hardware': section(dict(vcpus=2, ram=2048)),
            'ports': section([dict(id='port-'+ident['native_id'], device_id=ident['native_id'], network_id='net-a',
                fixed_ips=[dict(subnet_id='subnet-a', ip_address='10.250.91.4')])]),
            'networks': section([dict(id='net-a', name='Private LAN')]),
            'subnets': section([dict(id='subnet-a', network_id='net-a', cidr='10.250.91.0/24')]),
            'floatingips': section([dict(id='fip-a', floating_ip_address='94.26.228.219',
                fixed_ip_address='10.250.91.4', port_id='port-'+ident['native_id'])]),
            'volumes': section([dict(id='volume-'+ident['native_id'], name='System disk', size=50,
                attachments=[dict(server_id=ident['native_id'])])]),
        })
        if not floating:
            snapshot['sections']['floatingips']['data'] = []
        record = ProviderInventory.objects.create(provider_key=provider_key(ident, 'vm'), account=account,
            snapshot=snapshot, evidence_digest='a'*64, observed_at=timezone.now())
        review = native_prepare(admin, account)
        assert next(r for r in review['resources'] if r['key'] == record.pk)['action'] == 'create'
        native_apply(admin, account, uuid4(), review['fingerprint'])
        binding = ProviderBinding.objects.get(provider_key=record.pk)
        vm = VirtualMachine.objects.get(pk=binding.object_id)
        assert vm.status == 'offline' and vm.site.name.endswith('ru-9 — зона не указана')
        return record, binding, vm

    for cycle in range(2):
        record, binding, vm = new_cloud()
        initial = (VMInterface.objects.count(), IPAddress.objects.count(), VirtualDisk.objects.count())
        with patch('netbox_guard.provider_components.create_native', side_effect=ValueError('component rollback')):
            rejected(lambda: project_components(admin, binding, vm, record.snapshot), (ValueError,))
        assert initial == (VMInterface.objects.count(), IPAddress.objects.count(), VirtualDisk.objects.count())
        projected = project_components(admin, binding, vm, record.snapshot)
        assert not projected['notes'], projected
        vm.refresh_from_db()
        primary = vm.primary_ip4_id
        assert str(vm.primary_ip4.address.ip) == '94.26.228.219'
        assert vm.primary_ip4.nat_inside.assigned_object.virtual_machine_id == vm.pk
        assert VirtualDisk.objects.get(virtual_machine=vm).size == 50 * 1024**3 // 1000000
        counts = (VMInterface.objects.count(), IPAddress.objects.count(), VirtualDisk.objects.count(), VRF.objects.count())
        assert not project_components(admin, binding, vm, record.snapshot)['primary_updated']
        assert counts == (VMInterface.objects.count(), IPAddress.objects.count(), VirtualDisk.objects.count(), VRF.objects.count())
        assert vm.primary_ip4_id == primary
        from tenancy.models import Tenant
        network_vrf = vm.primary_ip4.nat_inside.vrf
        assert network_vrf.tenant_id == vm.tenant_id
        network_proof = ProviderCreatedObject.objects.get(model_label='ipam.vrf', object_id=network_vrf.pk)
        managed_tenant = network_vrf.tenant_id
        # Simulate upgrading a pre-tenancy proof with an operator-assigned tenant.
        network_proof.projection_values.pop('tenant_id')
        network_proof.save(update_fields=['projection_values'])
        operator_tenant = Tenant.objects.create(name='Manual network tenant ' + str(cycle), slug='manual-network-' + str(cycle))
        network_vrf.tenant = operator_tenant
        network_vrf.save(update_fields=['tenant'])
        project_components(admin, binding, vm, record.snapshot)
        network_vrf.refresh_from_db()
        network_proof.refresh_from_db()
        assert network_vrf.tenant_id == operator_tenant.pk
        assert 'tenant_id' not in network_proof.projection_values
        network_vrf.tenant_id = None
        network_vrf.save(update_fields=['tenant'])
        project_components(admin, binding, vm, record.snapshot)
        network_vrf.refresh_from_db()
        assert network_vrf.tenant_id == managed_tenant
        from netbox_guard.provider_resource_graph import document as graph_document
        graph = graph_document(admin, component_account)
        assert {'assigned_to', 'nat_to', 'attached_to'} <= {e['kind'] for e in graph['edges']}
        # Manual component edits block destructive cleanup and are never overwritten.
        disk = VirtualDisk.objects.get(virtual_machine=vm)
        old_name = disk.name
        disk.name = 'Operator disk name'; disk.save()
        assert 'component_edited' in project_components(admin, binding, vm, record.snapshot)['notes']
        assert any(b['reason'] == 'binding_target_changed' for b in lifecycle_review(admin, component_account, 'delete')['blockers'])
        disk.name = old_name; disk.save()
        deletion = lifecycle_review(admin, component_account, 'delete')
        assert not deletion['blockers'], deletion['blockers']
        nonce = uuid4()
        lifecycle_execute(admin, component_account, 'delete', nonce, deletion['fingerprint'])
        assert lifecycle_execute(admin, component_account, 'delete', nonce, deletion['fingerprint'])['replayed']
        assert not VirtualMachine.objects.filter(pk=vm.pk).exists()
        assert not ProviderCreatedObject.objects.filter(account=component_account).exists()
        assert initial == (VMInterface.objects.count(), IPAddress.objects.count(), VirtualDisk.objects.count())
        activate = lifecycle_review(admin, component_account, 'activate')
        lifecycle_execute(admin, component_account, 'activate', uuid4(), activate['fingerprint'])
    # Equal private IP/network identifiers in two accounts stay isolated.
    first, first_binding, first_vm = new_cloud('987654323', floating=False)
    second, second_binding, second_vm = new_cloud('987654324', floating=False)
    for record, binding, vm in ((first, first_binding, first_vm), (second, second_binding, second_vm)):
        assert not project_components(admin, binding, vm, record.snapshot)['notes']
        vm.refresh_from_db()
        assert str(vm.primary_ip4.address.ip) == '10.250.91.4'
    assert first_vm.primary_ip4.vrf_id != second_vm.primary_ip4.vrf_id
    second_primary = second_vm.primary_ip4_id
    deletion = lifecycle_review(admin, first.account, 'delete')
    assert not deletion['blockers'], deletion['blockers']
    lifecycle_execute(admin, first.account, 'delete', uuid4(), deletion['fingerprint'])
    second_vm.refresh_from_db()
    assert second_vm.primary_ip4_id == second_primary and IPAddress.objects.filter(pk=second_primary).exists()
    deletion = lifecycle_review(admin, second.account, 'delete')
    lifecycle_execute(admin, second.account, 'delete', uuid4(), deletion['fingerprint'])
    # Unlinking one VM keeps shared subnet/VRF context used by a second VM.
    from ipam.models import Prefix
    first, first_binding, first_vm = new_cloud('987654325', floating=False)
    second, second_binding, second_vm = new_cloud('987654325', floating=False)
    second.snapshot['sections']['ports']['data'][0]['fixed_ips'][0]['ip_address'] = '10.250.91.5'
    second.save(update_fields=['snapshot'])
    for record, binding, vm in ((first, first_binding, first_vm), (second, second_binding, second_vm)):
        assert not project_components(admin, binding, vm, record.snapshot)['notes']
        vm.refresh_from_db()
    shared_vrf = second_vm.primary_ip4.vrf_id
    unlink = lifecycle_review(admin, first.account, 'unlink', first.pk)
    assert not unlink['blockers'], unlink['blockers']
    lifecycle_execute(admin, first.account, 'unlink', uuid4(), unlink['fingerprint'], first.pk)
    assert VirtualMachine.objects.filter(pk=second_vm.pk).exists()
    assert Prefix.objects.filter(vrf_id=shared_vrf).exists()
    deletion = lifecycle_review(admin, first.account, 'delete')
    assert not deletion['blockers'], deletion['blockers']
    lifecycle_execute(admin, first.account, 'delete', uuid4(), deletion['fingerprint'])
print('Native cloud region fallback, port/IP/NAT/primary/disk projection, idempotence, rollback and two account cycles OK')
