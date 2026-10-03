"""Switch only managed JSON field visibility; never rewrite inventory values."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.template.loader import get_template
from extras.models import CustomField
from netbox_guard.display import FIELD_LABELS


class Command(BaseCommand):
    help = 'Preview/apply readable Sync panels; --raw restores standard JSON display.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--raw', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        get_template('netbox_guard/sync_details.html')
        rows = list(CustomField.objects.select_for_update().filter(name__in=FIELD_LABELS))
        allowed = {'dcim.device', 'dcim.interface', 'virtualization.virtualmachine',
                   'virtualization.vminterface'}
        for field in rows:
            types = {f'{t.app_label}.{t.model}' for t in field.object_types.all()}
            if field.type != 'json' or not types.issubset(allowed):
                raise CommandError(f'Incompatible field: {field.name}; nothing changed')
        desired = 'always' if options['raw'] else 'hidden'
        for field in rows:
            self.stdout.write(f'{field.name}: {field.ui_visible} -> {desired}')
            if options['apply'] and field.ui_visible != desired:
                field.ui_visible = desired
                field.full_clean()
                field.save(update_fields=['ui_visible'])
        self.stdout.write('Applied; stored JSON unchanged.' if options['apply']
                          else 'Preview only. Use --apply to change visibility.')
