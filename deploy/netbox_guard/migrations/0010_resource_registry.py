from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('netbox_guard', '0009_provider_ipam')]
    operations = [
        migrations.CreateModel(name='ProviderResourceRegistry', fields=[
            ('account', models.CharField(max_length=20, primary_key=True, serialize=False)),
            ('revision', models.PositiveBigIntegerField(default=1)),
            ('observed_at', models.DateTimeField()),
            ('evidence_digest', models.CharField(max_length=64)),
            ('snapshot', models.JSONField()),
        ], options={'default_permissions': (), 'permissions': [
            ('view_resourceregistry', 'View all provider resource registries'),
            ('manage_resourceregistry', 'Import provider resource registries')]}),
        migrations.CreateModel(name='ProviderResourceRegistryChange', fields=[
            ('nonce', models.UUIDField(primary_key=True, serialize=False)),
            ('actor', models.CharField(max_length=128)), ('digest', models.CharField(max_length=64)),
            ('revision', models.PositiveBigIntegerField()), ('before', models.JSONField(null=True)),
            ('after', models.JSONField()), ('result', models.JSONField()),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('registry', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                          to='netbox_guard.providerresourceregistry')),
        ], options={'default_permissions': ()}),
    ]
