"""Reconcile individual guest disks by source/VM/provider disk identity."""
from .netbox_vm_metadata import find_vm_sync_identity_matches
from .source_identity import virtual_machine_source_identity
from .network_scopes import object_id


class DiskSizeUnknown(ValueError):
    """A named disk cannot be written without a positive observed capacity."""
    def __init__(self, vm, disk):
        self.vm_name = vm.original_name
        self.disk_name = disk.name
        self.external_id = virtual_machine_source_identity(vm).external_id + ':' + str(disk.external_id or disk.name)
        super().__init__('Disk size is unknown')


def apply_virtual_disks(api,hosts,config,*,confirmed=False):
    vms=list(api.virtualization.virtual_machines.all())
    existing=list(api.virtualization.virtual_disks.all())
    pending=[]
    for host in hosts:
        for vm in host.virtual_machines:
            matches=find_vm_sync_identity_matches(vms,vm)
            if len(matches)!=1: raise ValueError('Disk parent VM identity is not unique')
            parent=matches[0];identity=virtual_machine_source_identity(vm).to_record()
            seen=set()
            for disk in vm.disks:
                key=getattr(disk,'external_id',None) or disk.name
                if not key or key in seen: raise ValueError('Missing or duplicate provider disk identity')
                seen.add(key)
                wanted={**identity,'kind':'vm-disk','external_id':identity['external_id']+':'+str(key)}
                candidates=[d for d in existing if (getattr(d,'custom_fields',{}) or {}).get('sync_disk_identity')==wanted]
                if len(candidates)>1: raise ValueError('Duplicate NetBox disk identity')
                current=candidates[0] if candidates else None
                if current is not None and object_id(current.serialize().get('virtual_machine'))!=parent.id:
                    raise ValueError('Disk identity belongs to another VM')
                if any(d.id!=(current.id if current else None) and object_id(d.serialize().get('virtual_machine'))==parent.id and d.name==disk.name for d in existing):
                    raise ValueError('Disk name is already used by an unmanaged or different disk')
                if disk.size_bytes<=0: raise DiskSizeUnknown(vm, disk)
                desired=dict(name=disk.name,size=max(1,(disk.size_bytes+999999)//1000000),
                    custom_fields={**(getattr(current,'custom_fields',{}) or {}),'sync_disk_identity':wanted})
                if current is None: pending.append((None,dict(virtual_machine=parent.id,**desired)))
                else:
                    changes={k:v for k,v in desired.items() if current.serialize().get(k)!=v}
                    if changes: pending.append((current,changes))
    if confirmed:
        for current,changes in pending:
            if current is None: api.virtualization.virtual_disks.create(**changes)
            else: current.update(changes)
