"""Durable reviewed source retirement; no automatic activation of old tombstones."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
revision='0010_source_retirements'
down_revision='0009_source_identity_proof'
branch_labels=None
depends_on=None

def upgrade(schema):
    op.create_table('source_retirements',
        sa.Column('operation_id',UUID(as_uuid=True),primary_key=True),
        sa.Column('source_instance',sa.Text,nullable=False),
        sa.Column('actor_id',sa.Text,nullable=False),
        sa.Column('revision',sa.Text,nullable=False),
        sa.Column('guard_instance',UUID(as_uuid=True),nullable=False),
        sa.Column('plan',JSONB,nullable=False),
        sa.Column('state',sa.Text,nullable=False,server_default='READY'),
        sa.Column('receipt',JSONB),
        sa.Column('safe_code',sa.Text),
        sa.Column('remove_credentials',sa.Boolean),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('finished_at',sa.DateTime(timezone=True)),
        sa.CheckConstraint("state IN ('READY','SENDING','UNCERTAIN','SUCCEEDED','FINALIZED','BLOCKED')",name='retirement_state'),
        schema=schema)
    op.create_index('retirement_inflight_source','source_retirements',['source_instance'],unique=True,
                    postgresql_where=sa.text("state IN ('SENDING','UNCERTAIN','SUCCEEDED')"),schema=schema)

def downgrade(schema):
    raise RuntimeError('Retirement intent and receipt history cannot be discarded automatically')
