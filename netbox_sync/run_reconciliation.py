"""Explicit Admin acceptance of a new baseline, never a historical success claim."""
from uuid import UUID
from psycopg import sql
from psycopg.types.json import Jsonb
from .source_operations import source_gate
from .source_lifecycle import LifecycleError
from .netbox_catalog import fingerprint


from .run_gates import blocking_runs


class RunReconciliation:
    def __init__(self,store,remote):self.store,self.remote=store,remote

    def _local(self,connection,source):
        row=connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s').format(self.store.table('sources')),(source,)).fetchone()
        if not row:raise LifecycleError('SOURCE_NOT_FOUND')
        if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status='RUNNING'").format(self.store.table('sync_runs')),(source,)).fetchone():
            raise LifecycleError('SOURCE_OPERATION_ACTIVE')
        if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status='RUNNING'").format(self.store.table('source_operations')),(source,)).fetchone():
            raise LifecycleError('SOURCE_OPERATION_ACTIVE')
        runs=connection.execute(sql.SQL("SELECT run_id,status,finished_at,plan_digest,planner_version,error_code FROM {} WHERE source_instance=%s AND status IN ('OUTCOME_UNCERTAIN','PARTIALLY_APPLIED') ORDER BY run_id LIMIT 101").format(blocking_runs(connection,self.store.schema)),(source,)).fetchall()
        if len(runs)>100 or any(run['finished_at'] is None for run in runs):raise LifecycleError('RUN_RECONCILIATION_UNAVAILABLE')
        return row,[{**run,'run_id':str(run['run_id']),'finished_at':run['finished_at'].isoformat()} for run in runs]

    def _review(self,source,operation):
        with self.store.connect() as connection,source_gate(connection,self.store.schema,source):
            row,runs=self._local(connection,source)
            revision=self.store.revision(row)
            previous=connection.execute(sql.SQL('SELECT operation_id,actor_id,created_at,valid,array_agg(run_id ORDER BY run_id) AS runs FROM {} WHERE source_instance=%s GROUP BY operation_id,actor_id,created_at,valid ORDER BY created_at DESC LIMIT 100').format(self.store.table('run_reconciliations')),(source,)).fetchall()
            decisions=[dict(operation_id=str(item['operation_id']),actor_id=item['actor_id'],created_at=item['created_at'].isoformat(),valid=item['valid'],runs=[str(run) for run in item['runs']],historical_outcome='UNPROVED') for item in previous]
        observed=(self.remote.call('audit',operation,source_instance=source) if runs else
                  {'guard_instance':None,'result':{'source_instance':source,'objects':[],'historical_outcome':'UNPROVED'}})
        # This is present inventory/claim evidence, not reconstruction of old POSTs.
        result=dict(source_instance=source,revision=revision,runs=runs,decisions=decisions,guard_instance=observed['guard_instance'],
                    inventory=observed['result'],decision='ACCEPT_CURRENT_BASELINE',historical_outcome='UNPROVED',schedule_after=False)
        result['digest']=fingerprint(result)
        return result

    def review(self,source,operation):
        with self.store.lock(self.store.lock_path):return self._review(source,operation)

    def confirm(self,source,operation,actor,digest,acknowledgements):
        operation=UUID(str(operation))
        if (not isinstance(actor,str) or not actor or len(actor)>200
                or not isinstance(acknowledgements,dict) or any(type(value) is not bool for value in acknowledgements.values())
                or acknowledgements!={'old_writes_stopped':True,'outcome_stays_unknown':True,'fresh_plan_required':True}):
            raise LifecycleError('REQUEST_INVALID')
        with self.store.lock(self.store.lock_path):
            with self.store.connect() as connection:
                previous=connection.execute(sql.SQL('SELECT decision,actor_id,source_instance,valid FROM {} WHERE operation_id=%s LIMIT 1').format(self.store.table('run_reconciliations')),(operation,)).fetchone()
                if previous:
                    if not previous['valid'] or (previous['actor_id'],previous['source_instance'],previous['decision']['digest'])!=(actor,source,digest):raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
                    return dict(source_instance=source,status='BASELINE_ACCEPTED',historical_outcome='UNPROVED')
            reviewed=self._review(source,operation)
            if reviewed['digest']!=digest or not reviewed['runs']:raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
            with self.store.connect() as connection,source_gate(connection,self.store.schema,source):
                row,runs=self._local(connection,source)
                if self.store.revision(row)!=reviewed['revision'] or runs!=reviewed['runs']:raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
                for run in runs:
                    connection.execute(sql.SQL('INSERT INTO {} (run_id,source_instance,actor_id,operation_id,run_status,run_finished_at,decision) VALUES (%s,%s,%s,%s,%s,%s,%s)').format(self.store.table('run_reconciliations')),
                        (UUID(run['run_id']),source,actor,operation,run['status'],run['finished_at'],Jsonb({**reviewed,'acknowledgements':acknowledgements})))
                connection.execute(sql.SQL('UPDATE {} SET sync_enabled=false WHERE source_instance=%s').format(self.store.table('sources')),(source,))
                connection.execute(sql.SQL("UPDATE {} SET status='STALE',result=NULL,safe_error_code='PLAN_STALE',updated_at=clock_timestamp() WHERE source_instance=%s AND operation_kind='PLAN' AND status='READY'").format(self.store.table('source_operations')),(source,))
            return dict(source_instance=source,status='BASELINE_ACCEPTED',historical_outcome='UNPROVED')
