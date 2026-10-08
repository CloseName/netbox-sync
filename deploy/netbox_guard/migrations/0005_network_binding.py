from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('netbox_guard','0004_source_closure'), ('ipam','__first__'), ('virtualization','__first__')]
    operations = [
        migrations.CreateModel(name='NetworkBinding', fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('interface_key',models.CharField(max_length=64)),
            ('interface_id',models.PositiveBigIntegerField()),
            ('confirmed_at',models.DateTimeField(auto_now_add=True)),
            ('prefix',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='ipam.prefix')),
            ('vm',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to='virtualization.virtualmachine')),
        ],options={'default_permissions':(), 'constraints':[models.UniqueConstraint(fields=('vm','interface_key','prefix'),name='guard_network_binding')]}),
        migrations.CreateModel(name='AddressReservation',fields=[
            ('nonce',models.UUIDField(primary_key=True,serialize=False)),
            ('actor_id',models.PositiveBigIntegerField()),
            ('created_at',models.DateTimeField(auto_now_add=True)),
            ('binding',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to='netbox_guard.networkbinding')),
            ('address',models.OneToOneField(on_delete=django.db.models.deletion.SET_NULL,null=True,to='ipam.ipaddress')),
        ],options={'default_permissions':()}),
    ]
