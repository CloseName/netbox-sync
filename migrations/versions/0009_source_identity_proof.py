"""Append-only proof of legacy ESXi source identity verification."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision='0009_source_identity_proof'
down_revision='0008_registration_intents'
branch_labels=None
depends_on=None


def upgrade(schema):
    op.create_table('source_identity_verifications',
        sa.Column('operation_id',UUID(as_uuid=True),primary_key=True),
        sa.Column('source_instance',sa.Text,nullable=False),
        sa.Column('actor_id',sa.Text,nullable=False),
        sa.Column('revision',sa.Text,nullable=False),
        sa.Column('anchor',sa.Text,nullable=False),
        sa.Column('proof',sa.JSON,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('CURRENT_TIMESTAMP')),
        schema=schema)


def downgrade(schema):
    raise RuntimeError('Verified identity history cannot be discarded automatically')
