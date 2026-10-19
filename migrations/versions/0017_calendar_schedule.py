"""Optional Moscow calendar schedules, independent of source connection settings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = '0017_calendar_schedule'
down_revision = '0016_removal_queue'
branch_labels = depends_on = None


def upgrade(schema):
    op.add_column('sources', sa.Column('sync_calendar', JSONB, nullable=True), schema=schema)
    op.add_column('sources', sa.Column('schedule_changed_at', sa.DateTime(timezone=True),
        nullable=False, server_default=sa.text('now()')), schema=schema)
    op.create_check_constraint('calendar_is_object', 'sources',
        "sync_calendar IS NULL OR jsonb_typeof(sync_calendar) = 'object'", schema=schema)


def downgrade(schema):
    raise RuntimeError('Calendar schedules must be migrated explicitly before downgrade')
