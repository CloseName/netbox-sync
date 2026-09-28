"""Confirmed removal waits for existing work while fencing new admission."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
revision = '0016_removal_queue'
down_revision = '0015_registration_jobs'
branch_labels = depends_on = None


def upgrade(schema):
    op.create_table('source_removal_requests',
        sa.Column('source_instance', sa.Text, sa.ForeignKey(f'{schema}.sources.source_instance', ondelete='CASCADE'), primary_key=True),
        sa.Column('operation_id', UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('actor_id', sa.Text, nullable=False),
        sa.Column('revision', sa.Text, nullable=False),
        sa.Column('display_name', sa.Text, nullable=False),
        sa.Column('state', sa.Text, nullable=False, server_default='WAITING'),
        sa.Column('safe_code', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.CheckConstraint("state IN ('WAITING','BLOCKED')"),schema=schema)
    q = '"' + schema.replace('"','""') + '"'
    # Also fence stale scheduler snapshots that already passed admission checks.
    op.execute(sa.text(f"""CREATE FUNCTION {q}.guard_queued_run() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
      BEGIN
        -- Order after source_run_admission's advisory lock. Serialize with
        -- enqueue's source row lock so an old statement snapshot cannot admit
        -- a run after the removal pause commits.
        PERFORM 1 FROM {q}.sources WHERE source_instance=NEW.source_instance FOR SHARE;
        IF EXISTS (SELECT 1 FROM {q}.source_removal_requests WHERE source_instance=NEW.source_instance)
        THEN RAISE EXCEPTION 'SOURCE_RUN_REFUSED' USING ERRCODE='23514'; END IF;
        RETURN NEW;
      END $body$"""))
    op.execute(sa.text(f'REVOKE ALL ON FUNCTION {q}.guard_queued_run() FROM PUBLIC'))
    op.execute(sa.text(f'CREATE TRIGGER source_z_queued_run_admission BEFORE INSERT ON {q}.sync_runs FOR EACH ROW EXECUTE FUNCTION {q}.guard_queued_run()'))


def downgrade(schema):
    raise RuntimeError('Confirmed removal requests cannot be discarded')
