"""Native ports, disks, primary IP and repeated removal/reconnection, isolated DB."""
from netbox_guard.provider_components import apply as project_components
from netbox_guard.provider_lifecycle import review as lifecycle_review, execute as lifecycle_execute
from virtualization.models import VirtualDisk
from ipam.models import VRF

with transaction.atomic():
    component_account = '987654322'
    def new_cloud():
        ident = dict(account=component_account, kind='cloud_vm', native_id=str(uuid4()), project='p', region='ru-9')
        def section(data): return dict(status='collected', data=data)
        snapshot = dict(identity=ident, sections={
            'resource': section(dict(name='Regional cloud fixture', status='SHELVED_OFFLOADED')),
            'placement': dict(status='not_reported', data={}),
            'hardware': section(dict(vcpus=2, ram=2048)),
            'ports': section([dict(id='port-a', device_id=ident['native_id'], network_id='net-a',
                fixed_ips=[dict(subnet_id='subnet-a', ip_address='10.250.91.4')])]),
            'networks': section([dict(id='net-a', name='Private LAN')]),
            'subnets': section([dict(id='subnet-a', network_id='net-a', cidr='10.250.91.0/24')]),
            'floatingips': section([dict(id='fip-a', floating_ip_address='94.26.228.219',
                fixed_ip_address='10.250.91.4', port_id='port-a')]),
            'volumes': section([dict(id='volume-a', name='System disk', size=50,
                attachments=[dict(server_id=ident['native_id'])])]),
        })
        record = ProviderInventory.objects.create(provider_key=provider_key(ident, 'vm'), account=component_account,
            snapshot=snapshot, evidence_digest='a'*64, observed_at=timezone.now())
        review = native_prepare(admin, component_account)
        assert review['resources'][0]['action'] == 'create'
        native_apply(admin, component_account, uuid4(), review['fingerprint'])
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
    transaction.set_rollback(True)
print('Native cloud region fallback, port/IP/NAT/primary/disk projection, idempotence, rollback and two account cycles OK')
