from django.db import migrations


SQL = """
CREATE FUNCTION netbox_guard_provider_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_binding_id bigint; claim record; actual jsonb; field_name text;
BEGIN
  SELECT id INTO v_binding_id FROM netbox_guard_providerbinding
    WHERE resource = TG_ARGV[0] AND object_id = CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END;
  IF TG_OP = 'DELETE' THEN
    IF v_binding_id IS NOT NULL THEN
      RAISE EXCEPTION 'PROVIDER_BINDING_DELETE_BLOCKED' USING ERRCODE = '23514';
    END IF;
    RETURN OLD;
  END IF;
  -- Projections cannot be forged through native API, bulk updates or forms.
  FOREACH field_name IN ARRAY ARRAY['selectel_refs', 'selectel_summary'] LOOP
    actual := COALESCE(NEW.custom_field_data -> field_name, 'null'::jsonb);
    IF actual <> 'null'::jsonb AND NOT EXISTS (
      SELECT 1 FROM netbox_guard_providerfieldclaim
      WHERE binding_id = v_binding_id AND field = 'custom_fields.' || field_name
    ) THEN
      RAISE EXCEPTION 'PROVIDER_PROJECTION_UNCLAIMED' USING ERRCODE = '23514';
    END IF;
  END LOOP;
  FOR claim IN SELECT field, value FROM netbox_guard_providerfieldclaim
    WHERE binding_id = v_binding_id LOOP
    IF claim.field LIKE 'custom_fields.%' THEN
      actual := NEW.custom_field_data -> substring(claim.field from 15);
    ELSE
      actual := to_jsonb(NEW) -> claim.field;
    END IF;
    IF COALESCE(actual, 'null'::jsonb) IS DISTINCT FROM COALESCE(claim.value, 'null'::jsonb) THEN
      RAISE EXCEPTION 'PROVIDER_FIELD_OWNED' USING ERRCODE = '23514';
    END IF;
  END LOOP;
  RETURN NEW;
END;
$$;
CREATE TRIGGER netbox_guard_provider_write BEFORE INSERT OR UPDATE OR DELETE ON dcim_device
FOR EACH ROW EXECUTE FUNCTION netbox_guard_provider_write('device');
CREATE TRIGGER netbox_guard_provider_write BEFORE INSERT OR UPDATE OR DELETE ON virtualization_virtualmachine
FOR EACH ROW EXECUTE FUNCTION netbox_guard_provider_write('vm');
"""


class Migration(migrations.Migration):
    dependencies = [('netbox_guard', '0006_provider_bindings'),
                    ('dcim', '__first__'), ('virtualization', '__first__')]
    operations = [migrations.RunSQL(SQL, """
        DROP TRIGGER netbox_guard_provider_write ON dcim_device;
        DROP TRIGGER netbox_guard_provider_write ON virtualization_virtualmachine;
        DROP FUNCTION netbox_guard_provider_write();
    """)]
