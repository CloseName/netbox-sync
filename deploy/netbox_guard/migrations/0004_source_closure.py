from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[('netbox_guard','0003_audit_permission')]
    operations=[migrations.CreateModel(name='SourceClosure',fields=[
        ('source_instance',models.CharField(max_length=128,primary_key=True,serialize=False)),
        ('created_at',models.DateTimeField(auto_now_add=True)),
        ('intent',models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,to='netbox_guard.retirementintent')),
    ],options={'default_permissions':()})]
