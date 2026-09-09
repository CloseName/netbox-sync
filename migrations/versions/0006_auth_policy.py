"""Server local identities and online onboarding destination policy."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0006_auth_policy'
down_revision = '0005_source_tombstones'
branch_labels = None
depends_on = None


def upgrade(schema):
    op.create_table('auth_state', sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('value', JSONB, nullable=False), sa.CheckConstraint('id=1'), schema=schema)
    state = {'principal': None, 'invitation': None, 'sessions': {}, 'attempts': [],
             'revision': 0, 'mode': 'legacy', 'ceiling': None, 'allowed_hosts': [],
             'denied_cidrs': [], 'changes': {}, 'receipts': {}}
    table = sa.table('auth_state', sa.column('id', sa.Integer), sa.column('value', JSONB), schema=schema)
    op.bulk_insert(table, [{'id': 1, 'value': state}])
    op.create_table('auth_audit', sa.Column('id', sa.BigInteger, primary_key=True),
        sa.Column('event', JSONB, nullable=False), schema=schema)


def downgrade(schema):
    raise RuntimeError('Administrative identities and audit cannot be discarded automatically')
