"""Immutable non-secret intent for actor-bound registration continuation."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision='0008_registration_intents'
down_revision='0007_host_reservations'
branch_labels=None
depends_on=None


def upgrade(schema):
    op.create_table('registration_intents',
        sa.Column('source_instance',sa.Text,primary_key=True),
        sa.Column('operation_id',UUID(as_uuid=True),nullable=False,unique=True),
        sa.Column('actor_id',sa.Text,nullable=False),
        sa.Column('anchor',sa.Text,nullable=False),
        sa.Column('fingerprint',sa.Text,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.CheckConstraint("fingerprint ~ '^[a-f0-9]{64}$'"),
        sa.ForeignKeyConstraint(['source_instance'],[schema+'.host_reservations.source_instance']),
        schema=schema)


def downgrade(schema):
    raise RuntimeError('Registration intent cannot be discarded automatically')
