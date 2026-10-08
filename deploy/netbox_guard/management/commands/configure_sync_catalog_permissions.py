"""One-time, explicit operator provisioning of shared catalog view/add rights."""
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from users.models import ObjectPermission

CATALOG_MODELS = (
    ('dcim', 'manufacturer'), ('dcim', 'devicetype'), ('dcim', 'devicerole'),
    ('dcim', 'platform'), ('virtualization', 'clustertype'),
)


class Command(BaseCommand):
    help = 'Grant only view/add for five shared Sync catalogs to an existing Apply user.'

    def add_arguments(self, parser):
        parser.add_argument('--user', required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options['user']).first()
        if user is None:
            raise CommandError('Apply user does not exist; no user was created.')
        name = 'NetBox Sync catalog preparation / ' + user.username
        permission, created = ObjectPermission.objects.get_or_create(name=name, defaults={
            'actions': ['view', 'add'], 'constraints': None,
        })
        wanted = {ContentType.objects.get(app_label=app, model=model).pk for app, model in CATALOG_MODELS}
        if not created and (set(permission.actions) != {'view', 'add'} or permission.constraints
                            or set(permission.object_types.values_list('pk', flat=True)) != wanted):
            raise CommandError('Existing permission differs; review it instead of overwriting.')
        permission.object_types.set(wanted)
        permission.users.add(user)
        self.stdout.write('Catalog view/add ready. No delete, infrastructure change, or Guard ownership rights granted.')
