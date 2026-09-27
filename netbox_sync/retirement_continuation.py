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

    def __call__(self):
        store = self.coordinator.store
        operation = None
        try:
            with store.connect() as connection:
                row = connection.execute(sql.SQL("""SELECT r.*, s.name
                    FROM {} r JOIN {} s USING (source_instance)
                    WHERE r.state IN ('SENDING','UNCERTAIN','SUCCEEDED')
                      AND r.superseded_by IS NULL AND r.remove_credentials IS TRUE
                    ORDER BY (r.operation_id > %s) DESC, r.operation_id LIMIT 1""").format(
                        store.table('source_retirements'), store.table('sources')),
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
