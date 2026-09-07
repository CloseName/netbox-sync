"""Reserve removed source identities without deleting registry or run history."""
from alembic import op
import sqlalchemy as sa
revision = '0005_source_tombstones'
down_revision = '0004_source_operations'
branch_labels = None
depends_on = None


def upgrade(schema):
    # Frozen schema, independent of the runtime initializer.
    if not sa.inspect(op.get_bind()).has_table('source_tombstones', schema=schema):
        op.create_table('source_tombstones',
            sa.Column('source_instance', sa.Text, primary_key=True),
            sa.Column('display_name', sa.Text, nullable=False),
            sa.Column('removed_at', sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.text('clock_timestamp()')),
            sa.Column('credential_state', sa.Text, nullable=False),
            sa.CheckConstraint("credential_state IN ('RETAINED_BY_REQUEST','REMOVED',"
                               "'RETAINED_SHARED_OR_LEGACY','CLEANUP_FAILED')", name='credential_state_valid'),
            schema=schema)


    # Invoker function: only advisory locking and validation; no owner escalation.
    op.execute(sa.text(f'''CREATE FUNCTION "{schema}".guard_source_credential_refs()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $guard$
        BEGIN
          IF TG_OP = 'UPDATE' AND
             ROW(NEW.token_id_provider,NEW.token_id_key,NEW.token_secret_provider,NEW.token_secret_key)
             IS NOT DISTINCT FROM
             ROW(OLD.token_id_provider,OLD.token_id_key,OLD.token_secret_provider,OLD.token_secret_key)
          THEN RETURN NEW; END IF;
          PERFORM pg_advisory_xact_lock_shared(hashtextextended('netbox-sync:{schema}:credential-refs',0));
          IF EXISTS (SELECT 1 FROM "{schema}".sources s
             JOIN "{schema}".source_tombstones t USING (source_instance)
             WHERE (s.token_id_provider,s.token_id_key) IN
                   ((NEW.token_id_provider,NEW.token_id_key),(NEW.token_secret_provider,NEW.token_secret_key))
                OR (s.token_secret_provider,s.token_secret_key) IN
                   ((NEW.token_id_provider,NEW.token_id_key),(NEW.token_secret_provider,NEW.token_secret_key)))
          THEN RAISE EXCEPTION 'Credential reference is reserved' USING ERRCODE='23514'; END IF;
          RETURN NEW;
        END $guard$'''))
    op.execute(sa.text(f'''CREATE TRIGGER source_credential_refs_guard
        BEFORE INSERT OR UPDATE OF token_id_provider,token_id_key,token_secret_provider,token_secret_key
        ON "{schema}".sources FOR EACH ROW EXECUTE FUNCTION "{schema}".guard_source_credential_refs()'''))


def downgrade(schema):
    raise RuntimeError('Source identity reservations cannot be purged automatically')
