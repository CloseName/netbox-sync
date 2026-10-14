from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('netbox_guard', '0012_registry_object_permission')]
    operations = [migrations.CreateModel(name='ProviderCreatedObject', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('account', models.CharField(max_length=20, db_index=True)),
        ('model_label', models.CharField(max_length=100)),
        ('object_id', models.PositiveBigIntegerField()),
        ('object_created', models.DateTimeField()),
        ('provider_key', models.CharField(max_length=512, blank=True)),
        ('created_at', models.DateTimeField(auto_now_add=True)),
    ], options={'default_permissions': (), 'constraints': [
        models.UniqueConstraint(fields=('model_label', 'object_id'), name='guard_provider_created_object')
    ]})]
