from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('netbox_guard', '0015_provider_account_network_cleanup')]
    operations = [
        migrations.AddField('providercreatedobject', 'resource_key', models.CharField(max_length=512, blank=True)),
        migrations.AddField('providercreatedobject', 'projection_values', models.JSONField(default=dict)),
    ]
