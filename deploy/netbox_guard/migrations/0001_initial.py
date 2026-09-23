"""Independent creation provenance and immutable retirement evidence."""
import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name='CreationReceipt', fields=[
            ('nonce', models.UUIDField(primary_key=True, serialize=False)),
            ('actor', models.CharField(max_length=128)),
            ('source_instance', models.CharField(max_length=128)),
            ('resource', models.CharField(max_length=16)),
            ('object_id', models.PositiveBigIntegerField()),
            ('digest', models.CharField(max_length=64)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'default_permissions': (), 'permissions': [('create_creationreceipt', 'Create source-owned objects with atomic claims')]}),
        migrations.CreateModel(name='RetirementIntent', fields=[
            ('nonce', models.UUIDField(primary_key=True, serialize=False)),
            ('actor', models.CharField(max_length=128)),
            ('source_instance', models.CharField(max_length=128)),
            ('manifest', models.JSONField()),
            ('digest', models.CharField(max_length=64)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'default_permissions': (), 'permissions': [('retire_retirementintent', 'Execute guarded source retirement')]}),
        migrations.CreateModel(name='CreationClaim', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ('resource', models.CharField(max_length=16)),
            ('object_id', models.PositiveBigIntegerField()),
            ('source_instance', models.CharField(max_length=128)),
            ('cluster_id', models.PositiveBigIntegerField()),
            ('object_created', models.DateTimeField()),
            ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'default_permissions': (), 'constraints': [models.UniqueConstraint(fields=('resource','object_id'), name='guard_created_object')]}),
        migrations.CreateModel(name='RetirementReceipt', fields=[
            ('intent', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, primary_key=True, serialize=False, to='netbox_guard.retirementintent')),
            ('digest', models.CharField(max_length=64)),
            ('deleted', models.JSONField()),
            ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'default_permissions': ()}),
    ]
