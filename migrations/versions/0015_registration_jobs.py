"""Approved registration continuation, without credentials in PostgreSQL."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
revision = '0015_registration_jobs'
down_revision = '0014_source_purge'
branch_labels = depends_on = None


def upgrade(schema):
    op.create_table('registration_jobs',
        sa.Column('source_instance', sa.Text, primary_key=True),
        sa.Column('operation_id', UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('actor_id', sa.Text, nullable=False),
        sa.Column('payload', JSONB, nullable=False),
        sa.Column('state', sa.Text, nullable=False, server_default='STAGING'),
        sa.Column('safe_code', sa.Text),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.CheckConstraint("state IN ('STAGING','READY','BLOCKED','COMPLETED')"), schema=schema)
    q = '"' + schema.replace('"', '""') + '"'
    # Only the already constrained source purge can delete a source at runtime.
    # Keep the new durable journal inside its atomic cleanup transaction.
    op.execute(sa.text(f"""CREATE FUNCTION {q}.purge_registration_job() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
      BEGIN
        DELETE FROM {q}.registration_jobs WHERE source_instance=OLD.source_instance;
        RETURN OLD;
      END $body$"""))
    op.execute(sa.text(f'REVOKE ALL ON FUNCTION {q}.purge_registration_job() FROM PUBLIC'))
    op.execute(sa.text(f'CREATE TRIGGER source_registration_job_purge AFTER DELETE ON {q}.sources FOR EACH ROW EXECUTE FUNCTION {q}.purge_registration_job()'))


def downgrade(schema):
    raise RuntimeError('Approved registration jobs must not be discarded')
