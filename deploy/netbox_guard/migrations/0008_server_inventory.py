from importlib import import_module
from django.db import migrations, models

# Replace only the function, preserving the existing trigger instances.
OLD = import_module('netbox_guard.migrations.0007_provider_write_guard').SQL.split('CREATE TRIGGER', 1)[0]
OLD = OLD.replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1)
NEW = OLD.replace("'selectel_refs', 'selectel_summary'", """'selectel_refs', 'selectel_summary',
  'selectel_inventory', 'selectel_location', 'selectel_configuration', 'selectel_os',
  'selectel_networks', 'selectel_collection_status'""")


class Migration(migrations.Migration):
    dependencies = [('netbox_guard', '0007_provider_write_guard')]
    operations = [
        migrations.CreateModel(name='ProviderInventory', fields=[
            ('provider_key', models.CharField(max_length=512, primary_key=True, serialize=False)),
            ('account', models.CharField(max_length=128, db_index=True)),
            ('snapshot', models.JSONField()), ('observed_at', models.DateTimeField()),
            ('evidence_digest', models.CharField(max_length=64)),
        ], options={'default_permissions': ()}),
        migrations.CreateModel(name='ProviderInventoryImport', fields=[
            ('nonce', models.UUIDField(primary_key=True, serialize=False)),
            ('account', models.CharField(max_length=128, db_index=True)),
            ('actor', models.CharField(max_length=128)), ('digest', models.CharField(max_length=64)),
            ('result', models.JSONField()), ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'default_permissions': ()}),
        migrations.RunSQL(NEW, OLD),
    ]
