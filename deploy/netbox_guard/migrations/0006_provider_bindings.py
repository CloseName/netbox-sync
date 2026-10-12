from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('netbox_guard', '0005_network_binding')]
    operations = [
        migrations.CreateModel(name='ProviderBinding', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('provider_key', models.CharField(max_length=512, unique=True)),
            ('account', models.CharField(max_length=128)),
            ('resource', models.CharField(max_length=16)),
            ('object_id', models.PositiveBigIntegerField()),
            ('object_created', models.DateTimeField()),
            ('revision', models.PositiveBigIntegerField(default=1)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'default_permissions': (),
                    'permissions': [('manage_providerbinding', 'Review and accept provider bindings')],
                    'constraints': [models.UniqueConstraint(fields=('resource', 'object_id'), name='guard_provider_target')]}),
        migrations.CreateModel(name='ProviderFieldClaim', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('field', models.CharField(max_length=128)),
            ('value', models.JSONField(null=True)),
            ('binding', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='netbox_guard.providerbinding')),
        ], options={'default_permissions': (), 'constraints': [models.UniqueConstraint(fields=('binding', 'field'), name='guard_provider_field')]}),
        migrations.CreateModel(name='ProviderBindingChange', fields=[
            ('nonce', models.UUIDField(primary_key=True, serialize=False)),
            ('actor', models.CharField(max_length=128)),
            ('digest', models.CharField(max_length=64)),
            ('before', models.JSONField()), ('after', models.JSONField()),
            ('reason', models.CharField(max_length=500)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('binding', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='netbox_guard.providerbinding')),
        ], options={'default_permissions': ()}),
    ]
