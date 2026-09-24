"""Immutable non-secret request for registration continuation after browser loss."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0011_registration_requests'
down_revision='0010_source_retirements'
branch_labels=None
depends_on=None

def upgrade(schema):
    op.add_column('registration_intents',sa.Column('request',JSONB,nullable=True),schema=schema)

def downgrade(schema):
    raise RuntimeError('Persisted registration requests cannot be discarded automatically')
