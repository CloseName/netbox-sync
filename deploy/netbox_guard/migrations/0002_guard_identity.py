"""Bind the remote protocol to one durable NetBox installation identity."""
from uuid import uuid4
from django.db import migrations, models

def initialize(apps, schema_editor):
    apps.get_model('netbox_guard','GuardIdentity').objects.create(id=1,identifier=uuid4())

def refuse_reverse(apps, schema_editor):
    raise RuntimeError('Guard installation identity must not be discarded automatically')

class Migration(migrations.Migration):
    dependencies = [('netbox_guard','0001_initial')]
    operations = [
        migrations.CreateModel(name='GuardIdentity',fields=[
            ('id',models.PositiveSmallIntegerField(default=1,editable=False,primary_key=True,serialize=False)),
            ('identifier',models.UUIDField(unique=True)),
        ],options={'default_permissions':(), 'constraints':[models.CheckConstraint(condition=models.Q(id=1),name='guard_single_identity')]}),
        migrations.RunPython(initialize,refuse_reverse),
    ]
