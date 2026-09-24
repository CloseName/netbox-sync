"""Append-only administrative baseline decisions; historical outcomes stay intact."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID,JSONB
revision='0012_run_reconciliation'
down_revision='0011_registration_requests'
branch_labels=None
depends_on=None

def upgrade(schema):
    op.create_table('run_reconciliations',
        sa.Column('run_id',UUID(as_uuid=True),primary_key=True),
        sa.Column('source_instance',sa.Text,nullable=False),
        sa.Column('actor_id',sa.Text,nullable=False),
        sa.Column('operation_id',UUID(as_uuid=True),primary_key=True),
        sa.Column('run_status',sa.Text,nullable=False),
        sa.Column('run_finished_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('decision',JSONB,nullable=False),
        sa.Column('valid',sa.Boolean,nullable=False,server_default=sa.true()),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.CheckConstraint("run_status IN ('OUTCOME_UNCERTAIN','PARTIALLY_APPLIED')"),schema=schema)
    op.create_index('run_reconciliation_valid','run_reconciliations',['run_id'],unique=True,postgresql_where=sa.text('valid'),schema=schema)
    # SELECT-only view for gates. Neither changes nor hides historical Run History.
    name='"'+schema.replace('"','""')+'"'
    op.execute(sa.text(f'CREATE VIEW {name}.blocking_sync_runs AS SELECT r.* FROM {name}.sync_runs r WHERE NOT EXISTS (SELECT 1 FROM {name}.run_reconciliations a WHERE a.run_id=r.run_id AND a.source_instance=r.source_instance AND a.run_status=r.status AND a.run_finished_at=r.finished_at AND a.valid)'))
    op.execute(sa.text(f"CREATE VIEW {name}.recovery_schedule_blocks AS SELECT DISTINCT a.source_instance FROM {name}.run_reconciliations a WHERE a.valid AND NOT EXISTS (SELECT 1 FROM {name}.sync_runs r WHERE r.source_instance=a.source_instance AND r.trigger='manual' AND r.status='SUCCEEDED' AND r.started_at>a.created_at)"))


def downgrade(schema):
    raise RuntimeError('Run reconciliation audit cannot be discarded automatically')
