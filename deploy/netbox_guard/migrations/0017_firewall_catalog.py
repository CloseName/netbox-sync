from uuid import uuid4
from django.db import migrations, models
import django.db.models.deletion
import utilities.json


class Migration(migrations.Migration):
    dependencies = [('netbox_guard', '0016_provider_components'), ('virtualization', '__first__')]
    operations = [
        migrations.CreateModel(name='FirewallAppliance', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('observed_at', models.DateTimeField()), ('version', models.CharField(max_length=256)),
            ('coverage', models.JSONField(default=dict)), ('digest', models.CharField(max_length=64)),
            ('vm', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='virtualization.virtualmachine')),
        ], options={'default_permissions': ()}),
        migrations.CreateModel(name='FirewallObject', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('custom_field_data', models.JSONField(blank=True, default=dict, encoder=utilities.json.CustomFieldJSONEncoder)),
            ('uid', models.UUIDField(default=uuid4, unique=True, editable=False)),
            ('identity_key', models.CharField(max_length=80)), ('identity_kind', models.CharField(max_length=16)),
            ('component', models.CharField(max_length=32)), ('table', models.CharField(max_length=32)),
            ('category', models.CharField(max_length=16, db_index=True)), ('name', models.CharField(max_length=256)),
            ('position', models.PositiveIntegerField()), ('enabled', models.BooleanField(default=True)),
            ('state', models.CharField(max_length=16, default='current', db_index=True)),
            ('data', models.JSONField(default=dict)), ('first_seen', models.DateTimeField()), ('last_seen', models.DateTimeField()),
            ('appliance', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='entries', to='netbox_guard.firewallappliance')),
        ], options={'default_permissions': (), 'ordering': ('appliance_id', 'component', 'table', 'position', 'pk'),
                    'constraints': [models.UniqueConstraint(fields=('appliance', 'identity_key'), name='guard_firewall_identity')]}),
        migrations.CreateModel(name='FirewallReference', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('field', models.CharField(max_length=64)),
            ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='references', to='netbox_guard.firewallobject')),
            ('target', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='referenced_by', to='netbox_guard.firewallobject')),
        ], options={'default_permissions': (), 'constraints': [models.UniqueConstraint(fields=('source', 'target', 'field'), name='guard_firewall_reference')]}),
    ]
