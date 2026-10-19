from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('netbox_guard', '0010_resource_registry')]
    operations = [migrations.CreateModel(name='ProviderAccountRun', fields=[
        ('nonce', models.UUIDField(primary_key=True, serialize=False)),
        ('account', models.CharField(max_length=20)),
        ('actor', models.CharField(max_length=128)),
        ('digest', models.CharField(max_length=64)),
        ('result', models.JSONField()),
        ('created_at', models.DateTimeField(auto_now_add=True)),
    ], options={'default_permissions': ()})]
