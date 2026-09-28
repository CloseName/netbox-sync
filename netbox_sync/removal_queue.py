"""Wait for admitted work; never turn an uncertain write into deletion consent."""
from uuid import UUID
import logging
from psycopg import sql
from .source_lifecycle import LifecycleError
from .run_gates import blocking_runs


class RemovalQueue:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.store = coordinator.store
        self.after = UUID(int=0)

    @staticmethod
    def public(row):
        return {key:str(row[key]) for key in ('source_instance','operation_id','state')} | {
            'queued':True, 'safe_code':row['safe_code']}

    def enqueue(self, source, operation, actor, revision, confirmed):
        if confirmed is not True or not isinstance(actor,str) or not actor or len(actor)>200:
            raise LifecycleError('REQUEST_INVALID')
        operation=UUID(str(operation))
        # Do not wait on the long-lived manual apply advisory lock just to save
        # consent. Row locking serializes duplicate requests and metadata edits;
        # admitted operations finish, all later admissions see the durable fence.
        with self.store.connect() as connection:
            row=connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s FOR UPDATE').format(self.store.table('sources')),(source,)).fetchone()
            if not row:raise LifecycleError('SOURCE_NOT_FOUND')
            saved=connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s').format(self.store.table('source_removal_requests')),(source,)).fetchone()
            if saved:
                if saved['operation_id']==operation and saved['actor_id']==actor:
                    return self.public(saved)
                if saved['state']!='BLOCKED':
                    raise LifecycleError('SOURCE_RETIREMENT_PENDING')
            if self.store.revision(row)!=revision:raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
            if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status IN ('OUTCOME_UNCERTAIN','PARTIALLY_APPLIED')").format(blocking_runs(connection,self.store.schema)),(source,)).fetchone():
                raise LifecycleError('SOURCE_APPLY_UNCONFIRMED')
            if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND state='CREDENTIALS_PENDING'").format(self.store.table('source_recoveries')),(source,)).fetchone():
                raise LifecycleError('SOURCE_RECOVERY_OUTCOME_UNCERTAIN')
            if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND (state IN ('SENDING','UNCERTAIN','SUCCEEDED') OR (state='BLOCKED' AND safe_code='SOURCE_OPERATION_ACTIVE'))").format(self.store.table('source_retirements')),(source,)).fetchone():
                raise LifecycleError('SOURCE_RETIREMENT_PENDING')
            paused=connection.execute(sql.SQL('UPDATE {} SET sync_enabled=false WHERE source_instance=%s RETURNING *').format(self.store.table('sources')),(source,)).fetchone()
            values=(operation,actor,self.store.revision(paused),row['name'],source)
            if saved:
                saved=connection.execute(sql.SQL("UPDATE {} SET operation_id=%s,actor_id=%s,revision=%s,display_name=%s,state='WAITING',safe_code=NULL WHERE source_instance=%s RETURNING *").format(self.store.table('source_removal_requests')),values).fetchone()
            else:
                saved=connection.execute(sql.SQL('INSERT INTO {} (operation_id,actor_id,revision,display_name,source_instance) VALUES (%s,%s,%s,%s,%s) RETURNING *').format(self.store.table('source_removal_requests')),values).fetchone()
            return self.public(saved)

    def status(self, source, operation, actor):
        with self.store.connect() as connection:
            saved=connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s').format(self.store.table('source_removal_requests')),(source,)).fetchone()
            remote=connection.execute(sql.SQL('SELECT 1 FROM {} WHERE operation_id=%s AND source_instance=%s').format(self.store.table('source_retirements')),(UUID(str(operation)),source)).fetchone()
        if remote or not saved:
            return self.coordinator.status(source,operation,actor)
        if saved['operation_id']!=UUID(str(operation)) or saved['actor_id']!=actor:
            raise LifecycleError('RETIREMENT_CONFLICT')
        return self.public(saved)

    def reconcile_abandoned_reads(self, source):
        # Same 180-second admission lease as OperationStore.latest. This journal
        # contains read-only DISCOVERY/PLAN work, never an apply/write run.
        with self.store.connect() as connection:
            rows=connection.execute(sql.SQL("SELECT operation_kind,operation_id FROM {} WHERE source_instance=%s AND status='RUNNING' AND updated_at<clock_timestamp()-interval '180 seconds'").format(self.store.table('source_operations')),(source,)).fetchall()
            for row in rows:
                if row['operation_kind'] not in {'DISCOVERY','PLAN'}:continue
                key=f"netbox-sync:{self.store.schema}:operation:{source}:{row['operation_kind']}"
                if connection.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS free',(key,)).fetchone()['free']:
                    connection.execute(sql.SQL("UPDATE {} SET status='FAILED',safe_error_code='OPERATION_INTERRUPTED',result=NULL,updated_at=clock_timestamp(),finished_at=clock_timestamp() WHERE operation_id=%s AND status='RUNNING'").format(self.store.table('source_operations')),(row['operation_id'],))

    def tick(self):
        with self.store.connect() as connection:
            rows=connection.execute(sql.SQL("SELECT * FROM {} WHERE state='WAITING' ORDER BY (operation_id>%s) DESC,operation_id LIMIT 1").format(self.store.table('source_removal_requests')),(self.after,)).fetchall()
        for row in rows:
            source=row['source_instance'];operation=row['operation_id'];actor=row['actor_id']
            self.after=operation
            try:
                self.reconcile_abandoned_reads(source)
                with self.store.connect() as connection:
                    record=connection.execute(sql.SQL('SELECT * FROM {} WHERE operation_id=%s').format(self.store.table('source_retirements')),(operation,)).fetchone()
                if record is not None:
                    if record['state']=='BLOCKED':
                        raise LifecycleError(record['safe_code'] or 'RETIREMENT_BLOCKED')
                    if record['state']!='READY':continue  # existing continuation owns dispatched writes
                    review=self.coordinator.public(record)
                else:
                    review=self.coordinator.review(source,operation,actor,row['revision'],queued=True)
                self.coordinator.execute(source,operation,actor,review['digest'],row['display_name'],True)
            except LifecycleError as exc:
                # Active operations may end safely; their presence is not a fault.
                # Unknown/partial writes and ownership/dependency conflicts block.
                waiting={'SOURCE_OPERATION_ACTIVE','SOURCE_APPLY_ACTIVE','LIFECYCLE_UNAVAILABLE','RETIREMENT_UNAVAILABLE'}
                if exc.code not in waiting:
                    with self.store.connect() as connection:
                        connection.execute(sql.SQL("UPDATE {} SET state='BLOCKED',safe_code=%s WHERE source_instance=%s AND operation_id=%s").format(self.store.table('source_removal_requests')),(exc.code,source,operation))
            except Exception:
                # Transport/DB interruption preserves consent; no blind remote write.
                logging.getLogger(__name__).warning('removal_operation=%s code=LIFECYCLE_UNAVAILABLE',operation)
