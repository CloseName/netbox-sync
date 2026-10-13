from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('netbox_guard', '0011_provider_account_run')]
    operations = [migrations.AlterModelOptions(
        name='providerresourceregistry',
        options={'default_permissions': (), 'permissions': [
            ('view_resourceregistry', 'View all provider resource registries'),
            ('manage_resourceregistry', 'Import provider resource registries'),
            ('manage_providerresourceregistry', 'Import provider resource registries (NetBox object permission)'),
        ]},
    )]
