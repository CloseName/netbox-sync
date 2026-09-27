"""Constrained local purge after exact full-retirement and filesystem evidence."""
from alembic import op
import sqlalchemy as sa
revision = '0014_source_purge'
down_revision = '0013_source_archives'
branch_labels = None
depends_on = None


def upgrade(schema):
    q = '"' + schema.replace('"', '""') + '"'
    op.add_column('source_retirements', sa.Column('local_cleanup_verified', sa.Boolean,
        nullable=False, server_default=sa.false()), schema=schema)
    # Fixed qualified objects and pg_catalog-only search path. Runtime roles
    # receive EXECUTE on this operation, never general source/history DELETE.
    op.execute(sa.text(f"""CREATE FUNCTION {q}.purge_retired_source(p_source text, p_operation uuid, p_actor text)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
        DECLARE r {q}.source_retirements%ROWTYPE;
        BEGIN
          IF NOT pg_try_advisory_xact_lock(hashtextextended('netbox-sync:{schema}:legacy-admission',0))
          THEN RAISE EXCEPTION 'SOURCE_PURGE_REFUSED'; END IF;
          PERFORM pg_advisory_xact_lock(hashtextextended('netbox-sync:{schema}:source:' || p_source,0));
          SELECT * INTO r FROM {q}.source_retirements
            WHERE operation_id=p_operation AND source_instance=p_source AND actor_id=p_actor FOR UPDATE;
          IF NOT FOUND OR r.state<>'SUCCEEDED' OR r.remove_credentials IS NOT TRUE
             OR r.local_cleanup_verified IS NOT TRUE OR r.superseded_by IS NOT NULL
             OR r.receipt IS NULL OR r.receipt->>'status' IS DISTINCT FROM 'SUCCEEDED'
             OR r.receipt->>'generation_closed' IS DISTINCT FROM 'true'
             OR r.receipt->'manifest'->>'format' IS DISTINCT FROM '2'
             OR r.receipt->>'source_instance' IS DISTINCT FROM p_source
             OR r.receipt->>'nonce' IS DISTINCT FROM p_operation::text
             OR r.receipt->>'digest' IS DISTINCT FROM r.plan->'remote'->>'digest'
             OR r.receipt->'manifest' IS DISTINCT FROM r.plan->'remote'->'manifest'
             OR NOT EXISTS (SELECT 1 FROM {q}.source_tombstones WHERE source_instance=p_source
                AND restored_at IS NULL AND credential_state IN ('REMOVED','RETAINED_SHARED_OR_LEGACY'))
             OR NOT EXISTS (SELECT 1 FROM {q}.sources WHERE source_instance=p_source AND NOT enabled AND NOT sync_enabled)
             OR EXISTS (SELECT 1 FROM {q}.source_operations WHERE source_instance=p_source AND status='RUNNING')
             OR EXISTS (SELECT 1 FROM {q}.blocking_sync_runs WHERE source_instance=p_source AND status IN ('RUNNING','OUTCOME_UNCERTAIN','PARTIALLY_APPLIED'))
             OR EXISTS (SELECT 1 FROM {q}.source_recoveries WHERE source_instance=p_source AND state='CREDENTIALS_PENDING')
          THEN RAISE EXCEPTION 'SOURCE_PURGE_REFUSED'; END IF;
          UPDATE {q}.auth_state SET value=jsonb_set(value,'{{source_teams}}',
            jsonb_set(value->'source_teams','{{assignments}}',(value->'source_teams'->'assignments')-p_source)
              || jsonb_build_object('revision',COALESCE((value->'source_teams'->>'revision')::bigint,0)+1))
            WHERE id=1 AND value->'source_teams'->'assignments' ? p_source;
          DELETE FROM {q}.auth_audit WHERE event->>'source_instance'=p_source;
          DELETE FROM {q}.run_reconciliations WHERE source_instance=p_source;
          DELETE FROM {q}.sync_runs WHERE source_instance=p_source;
          DELETE FROM {q}.source_operations WHERE source_instance=p_source;
          DELETE FROM {q}.source_identity_verifications WHERE source_instance=p_source;
          DELETE FROM {q}.source_recoveries WHERE source_instance=p_source;
          DELETE FROM {q}.registration_intents WHERE source_instance=p_source;
          DELETE FROM {q}.host_reservations WHERE source_instance=p_source;
          DELETE FROM {q}.source_archives WHERE source_instance=p_source;
          DELETE FROM {q}.source_tombstones WHERE source_instance=p_source;
          DELETE FROM {q}.source_retirements WHERE source_instance=p_source;
          DELETE FROM {q}.sources WHERE source_instance=p_source;
        END $body$"""))
    op.execute(sa.text(f'REVOKE ALL ON FUNCTION {q}.purge_retired_source(text,uuid,text) FROM PUBLIC'))
    # Auth retains no registry SELECT. Take the source lock before auth-state.
    op.execute(sa.text(f"""CREATE FUNCTION {q}.source_assignment_allowed(p_source text)
        RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
        BEGIN
          PERFORM pg_advisory_xact_lock(hashtextextended('netbox-sync:{schema}:source:' || p_source,0));
          RETURN EXISTS (SELECT 1 FROM {q}.sources s WHERE s.source_instance=p_source
            AND NOT EXISTS (SELECT 1 FROM {q}.source_tombstones t WHERE t.source_instance=s.source_instance AND t.restored_at IS NULL));
        END $body$"""))
    op.execute(sa.text(f'REVOKE ALL ON FUNCTION {q}.source_assignment_allowed(text) FROM PUBLIC'))


    # A stale scheduler snapshot must not recreate source-local history after the
    # source row is gone. The run writer retains no registry SELECT permission.
    op.execute(sa.text(f"""CREATE FUNCTION {q}.guard_run_source() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
        BEGIN
          PERFORM pg_advisory_xact_lock(hashtextextended('netbox-sync:{schema}:source:' || NEW.source_instance,0));
          IF NOT EXISTS (SELECT 1 FROM {q}.sources WHERE source_instance=NEW.source_instance)
             OR EXISTS (SELECT 1 FROM {q}.source_tombstones WHERE source_instance=NEW.source_instance AND restored_at IS NULL)
             OR EXISTS (SELECT 1 FROM {q}.source_archives WHERE source_instance=NEW.source_instance)
             OR EXISTS (SELECT 1 FROM {q}.source_retirements WHERE source_instance=NEW.source_instance
                        AND superseded_by IS NULL AND state IN ('SENDING','UNCERTAIN','SUCCEEDED'))
          THEN RAISE EXCEPTION 'SOURCE_RUN_REFUSED' USING ERRCODE='23514'; END IF;
          RETURN NEW;
        END $body$"""))
    op.execute(sa.text(f'REVOKE ALL ON FUNCTION {q}.guard_run_source() FROM PUBLIC'))
    op.execute(sa.text(f'CREATE TRIGGER source_run_admission BEFORE INSERT ON {q}.sync_runs FOR EACH ROW EXECUTE FUNCTION {q}.guard_run_source()'))


def downgrade(schema):
    raise RuntimeError('Purged source state cannot be reconstructed by a downgrade')
