"""Persist bounded latest PLAN and DISCOVERY operations separately from run history."""
from alembic import op
import sqlalchemy as sa

revision = '0004_source_operations'
down_revision = '0003_netbox_sync_naming'
branch_labels = None
depends_on = None


def upgrade(schema):
    op.create_table('source_operations',
        sa.Column('source_instance', sa.Text, primary_key=True),
        sa.Column('operation_kind', sa.Text, primary_key=True),
        sa.Column('operation_id', sa.UUID, nullable=False, unique=True),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('clock_timestamp()')),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.Column('safe_error_code', sa.Text),
        sa.Column('result', sa.JSON),
        sa.CheckConstraint("operation_kind IN ('PLAN','DISCOVERY')", name='operation_kind_valid'),
        sa.CheckConstraint("status IN ('RUNNING','READY','SUCCEEDED','FAILED','STALE')", name='operation_status_valid'),
        schema=schema)
    op.create_index('ix_source_operations_active', 'source_operations', ['updated_at'],
                    schema=schema, postgresql_where=sa.text("status='RUNNING'"))


def downgrade(schema):
    raise RuntimeError('Destructive operation-state downgrade is unsupported')
