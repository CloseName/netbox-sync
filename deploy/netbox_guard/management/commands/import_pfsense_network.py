"""Explicit operator import; preserves all fields except the pfSense snapshot."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.template.loader import get_template
from extras.models import CustomField
from virtualization.models import VirtualMachine, VMInterface
from netbox_guard.pfsense_preview import load_snapshot, build_preview
from netbox_guard.pfsense_network import FIELD, snapshot_record


class Command(BaseCommand):
    help = 'Preview or save a fresh pfSense network snapshot to one explicitly selected VM.'

    def add_arguments(self, parser):
        parser.add_argument('--vm', type=int, required=True)
        parser.add_argument('--snapshot', required=True)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            get_template('netbox_guard/pfsense_network.html')
            snapshot = load_snapshot(options['snapshot'])
            vm = VirtualMachine.objects.select_for_update().get(pk=options['vm'])
            interfaces = list(VMInterface.objects.select_for_update().filter(virtual_machine_id=vm.pk).order_by('pk')[:513])
            inventory = [dict(id=i.pk, vm_id=i.virtual_machine_id, name=i.name,
                              mac=str(i.primary_mac_address.mac_address) if i.primary_mac_address_id else None)
                         for i in interfaces]
            preview = build_preview(snapshot, inventory, vm.pk)
            if preview['unmatched_vm_interfaces']:
                raise ValueError('Some NetBox VM interfaces are absent from the snapshot')
            existing = (vm.custom_field_data or {}).get(FIELD)
            value = snapshot_record(preview, existing)
            field = CustomField.objects.select_for_update().filter(name=FIELD).first()
            if field is not None:
                types = {(t.app_label, t.model) for t in field.object_types.all()}
                if field.type != 'json' or types != {('virtualization', 'virtualmachine')}:
                    raise ValueError('Existing custom field has incompatible type or scope')
            self.stdout.write('VM {} ({}) | matched {}/{} | {}'.format(vm.pk, vm.name,
                len(preview['interfaces']), len(inventory), value['collected_at']))
            if not options['apply']:
                self.stdout.write('PREVIEW ONLY: snapshot would be {}'.format('unchanged' if value == existing else 'saved'))
                return
            if field is None:
                field = CustomField(name=FIELD, label='Сеть pfSense', type='json', group_name='NetBox Sync',
                                    required=False, ui_visible='hidden', ui_editable='no')
                field.full_clean()
                field.save()
                field.object_types.add(field.object_types.model.objects.get(app_label='virtualization', model='virtualmachine'))
            if value == existing:
                self.stdout.write('UNCHANGED: identical snapshot already stored')
                return
            vm.custom_field_data = {**(vm.custom_field_data or {}), FIELD: value}
            vm.full_clean()
            vm.save(update_fields=['custom_field_data', 'last_updated'])
            self.stdout.write('SAVED: pfsense_network; interface and IP objects unchanged')
        except (ValueError, OSError, VirtualMachine.DoesNotExist) as error:
            raise CommandError(str(error)) from None
