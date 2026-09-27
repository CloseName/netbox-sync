"""Separate immutable closed generations from active hardware reservations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
revision='0013_source_archives'
down_revision='0012_run_reconciliation'
branch_labels=None
depends_on=None

def upgrade(schema):
    op.create_table('source_archives',
        sa.Column('source_instance',sa.Text,primary_key=True),
        sa.Column('operation_id',UUID(as_uuid=True),nullable=False,unique=True),
        sa.Column('actor_id',sa.Text,nullable=False),
        sa.Column('mode',sa.Text,nullable=False),
        sa.Column('guard_instance',UUID(as_uuid=True),nullable=False),
        sa.Column('receipt',JSONB,nullable=False),
        sa.Column('verified_at',sa.DateTime(timezone=True),server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.CheckConstraint("mode IN ('FULL_DELETE','LEGACY_RETAIN')"),schema=schema)
    op.add_column('source_retirements',sa.Column('superseded_by',UUID(as_uuid=True)),schema=schema)
    op.drop_index('retirement_inflight_source',table_name='source_retirements',schema=schema)
    op.create_index('retirement_inflight_source','source_retirements',['source_instance'],unique=True,
                    postgresql_where=sa.text("state IN ('SENDING','UNCERTAIN','SUCCEEDED') AND superseded_by IS NULL"),schema=schema)
    op.add_column('host_reservations',sa.Column('released_at',sa.DateTime(timezone=True)),schema=schema)
    op.drop_constraint('host_reservations_pkey','host_reservations',schema=schema,type_='primary')
    op.create_primary_key('host_reservations_pkey','host_reservations',['provider','anchor','source_instance'],schema=schema)
    op.create_index('host_reservation_active','host_reservations',['provider','anchor'],unique=True,
                    postgresql_where=sa.text('released_at IS NULL'),schema=schema)
    # No external state is assumed during migration. Historical FINALIZED rows
    # must reconcile the pinned Guard receipt before releasing their identity.

def downgrade(schema):
    raise RuntimeError('Closed registration generations cannot be reopened automatically')
