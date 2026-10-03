"""Atomic snapshot-only import; never writes VM interfaces or IPAM objects."""
import json
from django.db import transaction
from rest_framework.response import Response
from virtualization.models import VirtualMachine, VMInterface
from extras.models import CustomField
from .views import GuardView
from ..dependencies import DependencyGuardBlocked
from ..pfsense_preview import build_preview
from ..pfsense_inventory import snapshot_record
from ..pfsense_network import snapshot_record as network_record

class PfSenseImport(GuardView):
    @transaction.atomic
    def post(self,request):
        if len(request.body)>8*1024*1024:raise DependencyGuardBlocked('REQUEST_TOO_LARGE')
        try:
            value=json.loads(request.body)
            if set(value)!={'vm_id','snapshot'} or type(value['vm_id']) is not int:raise ValueError()
            vm=VirtualMachine.objects.select_for_update().get(pk=value['vm_id'])
            if not request.user.has_perm('virtualization.change_virtualmachine',vm):
                raise DependencyGuardBlocked('PERMISSION_DENIED')
            if 'pfsense' not in vm.name.casefold():raise ValueError()
            interfaces=list(VMInterface.objects.select_for_update().filter(virtual_machine_id=vm.pk).order_by('pk')[:513])
            inventory=[dict(id=i.pk,vm_id=vm.pk,name=i.name,
                mac=str(i.primary_mac_address.mac_address) if i.primary_mac_address_id else None) for i in interfaces]
            preview=build_preview(value['snapshot']['network'],inventory,vm.pk)
            fields=dict(vm.custom_field_data or {})
            fields['pfsense_inventory']=snapshot_record(value['snapshot'],preview,fields.get('pfsense_inventory'))
            fields['pfsense_network']=network_record(preview,fields.get('pfsense_network'))
            for name,label in [('pfsense_inventory','Сервисы и правила pfSense'),('pfsense_network','Сеть pfSense')]:
                field=CustomField.objects.select_for_update().filter(name=name).first()
                if field is None:
                    if not request.user.has_perm('extras.add_customfield'):raise DependencyGuardBlocked('PERMISSION_DENIED')
                    field=CustomField(name=name,label=label,type='json',group_name='NetBox Sync',required=False,ui_visible='hidden',ui_editable='no')
                    field.full_clean();field.save()
                    field.object_types.add(field.object_types.model.objects.get(app_label='virtualization',model='virtualmachine'))
                elif field.type!='json' or {(t.app_label,t.model) for t in field.object_types.all()}!={('virtualization','virtualmachine')}:
                    raise ValueError()
            if fields==vm.custom_field_data:return Response({'status':'UNCHANGED'})
            vm.custom_field_data=fields;vm.full_clean();vm.save(update_fields=['custom_field_data','last_updated'])
            return Response({'status':'SAVED'})
        except (ValueError,KeyError,TypeError,VirtualMachine.DoesNotExist):
            raise DependencyGuardBlocked('PFSENSE_SNAPSHOT_INVALID') from None
