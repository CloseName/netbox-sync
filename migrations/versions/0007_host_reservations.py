"""Preserve provider identity reservations across uncertain registration outcomes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0007_host_reservations'
down_revision = '0006_auth_policy'
branch_labels = None
depends_on = None


def upgrade(schema):
    op.create_table('host_reservations',
        sa.Column('provider', sa.Text, primary_key=True),
        sa.Column('anchor', sa.Text, primary_key=True),
        sa.Column('source_instance', sa.Text, nullable=False, unique=True),
        sa.Column('operation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('actor_id', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.CheckConstraint("provider = 'esxi'"), schema=schema)

    op.add_column('source_tombstones', sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True), schema=schema)
    op.create_table('source_recoveries',
        sa.Column('operation_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('source_instance', sa.Text, nullable=False),
        sa.Column('actor_id', sa.Text, nullable=False),
        sa.Column('revision', sa.Text, nullable=False),
        sa.Column('plan', sa.JSON, nullable=False),
        sa.Column('state', sa.Text, nullable=False, server_default='PREPARED'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("state IN ('PREPARED','CREDENTIALS_PENDING','RESTORED','ABANDONED')"), schema=schema)
    op.create_index('source_recovery_active', 'source_recoveries', ['source_instance'], unique=True,
        schema=schema, postgresql_where=sa.text("state IN ('PREPARED','CREDENTIALS_PENDING')"))


def downgrade(schema):
    raise RuntimeError('Provider reservations cannot be discarded automatically')
