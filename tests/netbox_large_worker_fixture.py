"""Extra inventory only in the labelled, isolated real NetBox fixture."""
def grow(source,user):
    from uuid import uuid4
    from django.db import connection
    from netbox_guard.models import CreationClaim
    from netbox_guard.service import create_owned
    from virtualization.models import Cluster,VirtualMachine
    from dcim.models import Device
    assert connection.settings_dict['NAME']=='netbox_sync_guard_test'
    claim=CreationClaim.objects.get(source_instance=source,resource='cluster')
    cluster=Cluster.objects.get(pk=claim.object_id)
    host_claim=CreationClaim.objects.get(source_instance=source,resource='device')
    host=Device.objects.get(pk=host_claim.object_id,cluster=cluster)
    def create(kind,values):return create_owned(user,uuid4(),source,kind,values,cluster=cluster.pk)
    for index in range(276):
        vm=create('vm',dict(name=f'large-owned-{index}',cluster=cluster,device=host))
        nic=create('vminterface',dict(name='eth0',virtual_machine=vm))
        create('ip',dict(address=f'198.19.{index//250}.{index%250+1}/24',assigned_object=nic))
        create('mac',dict(mac_address=f'02:00:01:02:{index//256:02x}:{index%256:02x}',assigned_object=nic))
    result=dict(vms=VirtualMachine.objects.filter(cluster=cluster).count(),objects=CreationClaim.objects.filter(source_instance=source).count())
    assert result['vms']>=276 and result['objects']>=1099
    return result
