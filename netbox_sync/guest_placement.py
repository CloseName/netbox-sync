"""Attach managed guests to their identity-matched host; preserve cluster scope."""
from .netbox_metadata import find_sync_identity_matches
from .netbox_vm_metadata import find_vm_sync_identity_matches
from .network_scopes import object_id


def apply_guest_placement(api, hosts, config, *, confirmed=False):
    devices=list(api.dcim.devices.all())
    vms=list(api.virtualization.virtual_machines.all())
    pending=[]
    for host in hosts:
        matched=find_sync_identity_matches(devices,host)
        if not matched: continue  # Legacy/unmanaged hosts need explicit adoption first.
        if len(matched)!=1: raise ValueError('Ambiguous managed host identity')
        device=matched[0]
        for guest in [*host.virtual_machines,*host.containers]:
            # LXC uses a separate identity builder.
            if hasattr(guest,'architecture'):
                from .netbox_lxc_metadata import find_lxc_sync_identity_matches
                matches=find_lxc_sync_identity_matches(vms,guest)
            else: matches=find_vm_sync_identity_matches(vms,guest)
            if len(matches)!=1: raise ValueError('Guest placement identity is ambiguous or missing')
            vm=matches[0]
            current=object_id(vm.serialize().get('device'))
            if current==device.id: continue
            if current is not None:
                previous=next((d for d in devices if d.id==current),None)
                # Never replace an unrelated manually assigned host silently.
                owner={i.get('instance') for i in (getattr(previous,'custom_fields',{}) or {}).get('sync_identities',[]) if isinstance(i,dict)}
                if guest.source_instance not in owner: raise ValueError('Guest has an unrelated host assignment')
            if object_id(vm.serialize().get('cluster')) != object_id(device.serialize().get('cluster')):
                raise ValueError('Guest and managed host belong to different clusters')
            pending.append((vm,device.id))
    if confirmed:
        for vm,identifier in pending: vm.update({'device':identifier})
