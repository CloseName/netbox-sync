"""Restart-safe continuation of previously confirmed immutable retirement intents.

No credentials, remote response bodies or infrastructure values enter logs.
One item per tick avoids monopolizing the lifecycle socket. A rotating cursor
prevents an unavailable source from starving other confirmed operations.
"""
import logging
from uuid import UUID
from psycopg import sql
from .local_control import ControlError, SAFE_CODES
from .source_lifecycle import LifecycleError


class RetirementContinuation:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.after = UUID(int=0)
        from .removal_queue import RemovalQueue
        self.queue = RemovalQueue(coordinator)

    def __call__(self):
        store = self.coordinator.store
        operation = None
        try:
            self.queue.tick()
            with store.connect() as connection:
                # Resolve the active operation before legacy busy refusals; the DB
                # unique index permits only one active nonce per source.
                # Two legacy nonces must never race each other after a restart.
                pending="(r.state IN ('SENDING','UNCERTAIN','SUCCEEDED') OR (r.state='BLOCKED' AND r.safe_code='SOURCE_OPERATION_ACTIVE'))"
                older=pending.replace('r.','older.')
                row = connection.execute(sql.SQL("""SELECT r.*, s.name
                    FROM {} r JOIN {} s USING (source_instance)
                    WHERE """+pending+""" AND r.superseded_by IS NULL AND r.remove_credentials IS TRUE
                    AND NOT EXISTS (SELECT 1 FROM {} older WHERE older.source_instance=r.source_instance
                        AND older.superseded_by IS NULL AND """+older+"""
                        AND (CASE WHEN older.state='BLOCKED' THEN 1 ELSE 0 END,older.created_at,older.operation_id)
                          <(CASE WHEN r.state='BLOCKED' THEN 1 ELSE 0 END,r.created_at,r.operation_id))
                    ORDER BY (r.operation_id > %s) DESC, r.operation_id LIMIT 1""").format(
                        store.table('source_retirements'), store.table('sources'),store.table('source_retirements')),
                        (self.after,)).fetchone()
            if row is None:
                return
            operation = self.after = row['operation_id']
            self.coordinator.execute(row['source_instance'], operation, row['actor_id'],
                row['plan']['remote']['digest'], row['name'], True, resume=True)
        except (ControlError, LifecycleError) as error:
            code = error.code if error.code in SAFE_CODES else 'LIFECYCLE_UNAVAILABLE'
            logging.getLogger(__name__).warning(
                'retirement_operation=%s continuation=deferred code=%s', operation, code)
        except Exception:
            # Keep the journal and the socket available after transient DB faults.
            # Never log exception text (it may contain connection credentials).
            logging.getLogger(__name__).error(
                'retirement_operation=%s continuation=deferred code=LIFECYCLE_UNAVAILABLE', operation)
