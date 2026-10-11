"""Allow the distinct scheduled reconciliation outcome in durable history."""
from alembic import op

revision = '0018_reconciliation_code'
down_revision = '0017_calendar_schedule'
branch_labels = depends_on = None

ERROR_CODES = (
    'APPLY_LOCKED', 'PLAN_BLOCKED', 'PLAN_STALE', 'CONFIRMATION_EXPIRED',
    'CONFIRMATION_INVALID', 'CONFIRMATION_SOURCE_MISMATCH', 'FAILED_BEFORE_WRITE',
    'PARTIALLY_APPLIED', 'OUTCOME_UNCERTAIN', 'APPLY_FAILED',
    'SOURCE_RECONCILIATION_REQUIRED',
)


def upgrade(schema):
    op.drop_constraint('sync_runs_error_code', 'sync_runs', schema=schema, type_='check')
    allowed = ', '.join(repr(code) for code in ERROR_CODES)
    op.create_check_constraint('sync_runs_error_code', 'sync_runs',
                               f'error_code IS NULL OR error_code IN ({allowed})', schema=schema)


def downgrade(schema):
    raise RuntimeError('Reconciliation outcomes must be reviewed before downgrade')
