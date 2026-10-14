from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('netbox_guard', '0013_provider_creation_provenance')]
    operations = [
        migrations.CreateModel(name='ProviderDetachedResource', fields=[
            ('provider_key', models.CharField(max_length=512, primary_key=True, serialize=False)),
            ('account', models.CharField(max_length=20, db_index=True)),
        ], options={'default_permissions': ()}),
        migrations.CreateModel(name='ProviderAccountFence', fields=[
            ('account', models.CharField(max_length=20, primary_key=True, serialize=False)),
            ('deleted', models.BooleanField(default=False)),
        ], options={'default_permissions': ()}),
        migrations.CreateModel(name='ProviderLifecycleReceipt', fields=[
            ('nonce', models.UUIDField(primary_key=True, serialize=False)),
            ('account', models.CharField(max_length=20)), ('actor', models.CharField(max_length=128)),
            ('digest', models.CharField(max_length=64)), ('result', models.JSONField()),
            ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'default_permissions': ()}),
    ]
