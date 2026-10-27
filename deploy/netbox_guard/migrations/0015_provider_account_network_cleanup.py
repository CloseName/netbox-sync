"""Permit network claim removal only after its account is fenced deleted."""
from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION netbox_guard_ipam_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_account text;
BEGIN
  IF TG_OP = 'DELETE' AND TG_TABLE_NAME = 'netbox_guard_providernetworklink' THEN
    SELECT account INTO owner_account FROM netbox_guard_providerbinding WHERE id = OLD.binding_id;
  ELSIF TG_OP = 'DELETE' AND TG_TABLE_NAME = 'netbox_guard_provideripamobject' THEN
    IF (OLD.key::jsonb)->>0 = 'selectel' THEN
      owner_account := (OLD.key::jsonb)->>1;
    END IF;
    IF EXISTS (SELECT 1 FROM netbox_guard_providernetworklink WHERE native_id = OLD.id) THEN
      RAISE EXCEPTION 'PROVIDER_IPAM_LINKS_REMAIN' USING ERRCODE = '23514';
    END IF;
  END IF;
  IF owner_account IS NOT NULL AND EXISTS (
    SELECT 1 FROM netbox_guard_provideraccountfence WHERE account = owner_account AND deleted
  ) THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'PROVIDER_IPAM_RECORD_IMMUTABLE' USING ERRCODE = '23514';
END $$;
"""

REVERSE = """
CREATE OR REPLACE FUNCTION netbox_guard_ipam_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'PROVIDER_IPAM_RECORD_IMMUTABLE' USING ERRCODE = '23514';
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [('netbox_guard', '0014_provider_lifecycle')]
    operations = [migrations.RunSQL(SQL, REVERSE)]
