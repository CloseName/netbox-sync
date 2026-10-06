"""Fixed managed field presentation policy; never changes object values."""
import logging
from django.db import transaction
from extras.models import CustomField

LOGGER = logging.getLogger(__name__)
FIELDS = {'cpu_cores': ('integer', ('dcim.device',)),
 'cpu_model': ('text', ('dcim.device',)),
 'cpu_sockets': ('integer', ('dcim.device',)),
 'cpu_threads': ('integer', ('dcim.device',)),
 'cpu_vendor': ('text', ('dcim.device',)),
 'esxi_host_network': ('json', ('dcim.device',)),
 'guest_architecture': ('text', ('virtualization.virtualmachine',)),
 'guest_kind': ('text', ('virtualization.virtualmachine',)),
 'guest_os_type': ('text', ('virtualization.virtualmachine',)),
 'hypervisor_version': ('text', ('dcim.device',)),
 'memory_mb': ('integer', ('dcim.device',)),
 'pfsense_inventory': ('json', ('virtualization.virtualmachine',)),
 'pfsense_network': ('json', ('virtualization.virtualmachine',)),
 'physical_disks': ('json', ('dcim.device',)),
 'source_bridge': ('text', ('virtualization.vminterface',)),
 'source_vlan_id': ('integer', ('virtualization.vminterface',)),
 'swap_mb': ('integer', ('virtualization.virtualmachine',)),
 'sync_identities': ('json',
                     ('dcim.device',
                      'dcim.interface',
                      'virtualization.virtualmachine',
                      'virtualization.vminterface')),
 'sync_network_observations': ('json', ('virtualization.vminterface',)),
 'sync_original_names': ('json',
                         ('dcim.device',
                          'dcim.interface',
                          'virtualization.virtualmachine',
                          'virtualization.vminterface'))}


def compatible(field, kind, models):
    actual = {f'{t.app_label}.{t.model}' for t in field.object_types.all()}
    return (field.type == kind and actual == set(models)
            and field.group_name in ('', 'NetBox Sync')
            and not field.required and not field.unique)


@transaction.atomic
def configure_managed_fields(using='default'):
    """Run after migrations, before application workers accept imports."""
    for name, (kind, models) in FIELDS.items():
        field = CustomField.objects.using(using).select_for_update().filter(name=name).first()
        if field is None:
            # pfSense prerequisites belong to Guard; other fields belong to Sync setup.
            if name not in ('pfsense_inventory', 'pfsense_network'):
                continue
            field = CustomField(name=name, type=kind, group_name='NetBox Sync',
                                required=False, ui_visible='hidden', ui_editable='no')
            field.full_clean()
            field.save(using=using)
            field.object_types.add(field.object_types.model.objects.using(using).get(
                app_label='virtualization', model='virtualmachine'))
        if not compatible(field, kind, models):
            LOGGER.warning('NetBox Sync: incompatible custom field %s; unchanged', name)
            continue
        desired = 'hidden' if kind == 'json' else 'if-set'
        if field.ui_visible != desired or field.ui_editable != 'no':
            field.ui_visible = desired
            field.ui_editable = 'no'
            field.full_clean()
            field.save(using=using, update_fields=['ui_visible', 'ui_editable'])
