from django.db import migrations, models
import django.db.models.deletion

SQL = """
CREATE FUNCTION netbox_guard_ipam_write() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE record_claim record; field_name text; expected jsonb; candidate jsonb;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    FOR record_claim IN SELECT * FROM netbox_guard_provideripamobject
      WHERE kind = TG_ARGV[0] AND object_id = OLD.id LOOP
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'PROVIDER_IPAM_DELETE_BLOCKED' USING ERRCODE = '23514';
      END IF;
      candidate := to_jsonb(NEW);
      FOR field_name, expected IN SELECT * FROM jsonb_each(record_claim.claims) LOOP
        IF field_name = 'address' AND TG_ARGV[0] = 'ipaddress' THEN
          IF (candidate->>'address')::inet IS DISTINCT FROM (expected #>> '{}')::inet THEN
            RAISE EXCEPTION 'PROVIDER_IPAM_FIELD_OWNED' USING ERRCODE = '23514';
          END IF;
        ELSIF candidate -> field_name IS DISTINCT FROM expected THEN
          RAISE EXCEPTION 'PROVIDER_IPAM_FIELD_OWNED' USING ERRCODE = '23514';
        END IF;
      END LOOP;
    END LOOP;
  END IF;
  -- NetBox permits duplicate global IPs/prefixes in some configurations. Do not
  -- permit another writer to create an ambiguous alias of an accepted identity.
  IF TG_OP <> 'DELETE' AND TG_ARGV[0] = 'ipaddress' THEN
    IF EXISTS (SELECT 1 FROM netbox_guard_provideripamobject p
       WHERE p.kind = 'ipaddress' AND p.object_id <> NEW.id
         AND (p.claims->>'vrf_id') IS NOT DISTINCT FROM NEW.vrf_id::text
         AND host((p.claims->>'address')::inet) = host(NEW.address)) THEN
      RAISE EXCEPTION 'PROVIDER_IPAM_DUPLICATE' USING ERRCODE = '23514';
    END IF;
  ELSIF TG_OP <> 'DELETE' AND TG_ARGV[0] = 'prefix' THEN
    IF EXISTS (SELECT 1 FROM netbox_guard_provideripamobject p
       WHERE p.kind = 'prefix' AND p.object_id <> NEW.id
         AND (p.claims->>'vrf_id') IS NOT DISTINCT FROM NEW.vrf_id::text
         AND (p.claims->>'prefix')::cidr = NEW.prefix) THEN
      RAISE EXCEPTION 'PROVIDER_IPAM_DUPLICATE' USING ERRCODE = '23514';
    END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE FUNCTION netbox_guard_ipam_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'PROVIDER_IPAM_RECORD_IMMUTABLE' USING ERRCODE = '23514';
END $$;
"""
for kind in ('vlangroup', 'vlan', 'prefix', 'ipaddress'):
    SQL += f"CREATE TRIGGER guard_provider_ipam BEFORE INSERT OR UPDATE OR DELETE ON ipam_{kind} FOR EACH ROW EXECUTE FUNCTION netbox_guard_ipam_write('{kind}');\n"
for model in ('provideripamobject', 'providernetworklink', 'provideripamreceipt'):
    SQL += f"CREATE TRIGGER guard_provider_immutable BEFORE UPDATE OR DELETE ON netbox_guard_{model} FOR EACH ROW EXECUTE FUNCTION netbox_guard_ipam_immutable();\n"
REVERSE = '\n'.join(f'DROP TRIGGER guard_provider_ipam ON ipam_{k};' for k in ('vlangroup', 'vlan', 'prefix', 'ipaddress'))
REVERSE += '\n' + '\n'.join(f'DROP TRIGGER guard_provider_immutable ON netbox_guard_{k};' for k in ('provideripamobject', 'providernetworklink', 'provideripamreceipt'))
REVERSE += '\nDROP FUNCTION netbox_guard_ipam_write(); DROP FUNCTION netbox_guard_ipam_immutable();'


class Migration(migrations.Migration):
    dependencies = [('netbox_guard', '0008_server_inventory')]
    operations = [
        migrations.CreateModel(name='ProviderIPAMObject', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('key', models.CharField(max_length=512, unique=True)), ('kind', models.CharField(max_length=16)),
            ('object_id', models.PositiveBigIntegerField()), ('object_created', models.DateTimeField()),
            ('claims', models.JSONField()),
        ], options={'default_permissions': (), 'constraints': [models.UniqueConstraint(fields=('kind', 'object_id'), name='guard_provider_ipam_target')]}),
        migrations.CreateModel(name='ProviderNetworkLink', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('relation', models.CharField(max_length=16)), ('evidence', models.JSONField()),
            ('binding', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='netbox_guard.providerbinding')),
            ('native', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='netbox_guard.provideripamobject')),
        ], options={'default_permissions': (), 'constraints': [models.UniqueConstraint(fields=('binding', 'native', 'relation'), name='guard_provider_network_link')]}),
        migrations.CreateModel(name='ProviderIPAMReceipt', fields=[
            ('nonce', models.UUIDField(primary_key=True, serialize=False)),
            ('actor', models.CharField(max_length=128)), ('digest', models.CharField(max_length=64)),
            ('result', models.JSONField()), ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'default_permissions': ()}),
        migrations.RunSQL(SQL, REVERSE),
    ]
