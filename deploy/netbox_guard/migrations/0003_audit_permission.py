from django.db import migrations

class Migration(migrations.Migration):
    dependencies=[('netbox_guard','0002_guard_identity')]
    operations=[migrations.AlterModelOptions(name='retirementintent',options={
        'default_permissions':(), 'permissions':[
            ('retire_retirementintent','Execute guarded source retirement'),
            ('audit_retirementintent','Audit source ownership without retirement')]})]
