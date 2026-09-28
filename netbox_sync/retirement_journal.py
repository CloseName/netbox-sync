"""DB-only lifecycle journal. No NetBox token, HTTP client or secret filesystem.

The trusted coordinator supplies checked guard evidence. This module does
not itself perform retirement, activate old tombstones or authorize API callers.
"""
import json
from uuid import UUID
from .run_gates import blocking_runs
from .retirement_codes import DEFINITE_REFUSALS
from psycopg import sql
from psycopg.types.json import Jsonb
from .host_registration import identity_placement
from .source_operations import source_gate
from .source_lifecycle import LifecycleError


class RetirementJournal:
    def __init__(self,store): self.store=store

    def _row(self,connection,source):
        row=connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s').format(
            self.store.table('sources')),(source,)).fetchone()
        if row is None:raise LifecycleError('SOURCE_NOT_FOUND')
        return row

    def _guard(self,connection,source,revision,pending_flags=None, *, archive=False):
        row=self._row(connection,source)
        checked=row
        if pending_flags is not None:
            if row['enabled'] or row['sync_enabled']:raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
            checked={**row,**pending_flags}
        if self.store.revision(checked)!=revision:raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
        if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status='RUNNING'").format(
                self.store.table('source_operations')),(source,)).fetchone():
            raise LifecycleError('SOURCE_OPERATION_ACTIVE')
        if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status IN ('RUNNING','OUTCOME_UNCERTAIN','PARTIALLY_APPLIED')").format(
                blocking_runs(connection,self.store.schema)),(source,)).fetchone():
            raise LifecycleError('SOURCE_APPLY_UNCONFIRMED')
        if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND state='CREDENTIALS_PENDING'").format(self.store.table('source_recoveries')),(source,)).fetchone():raise LifecycleError('SOURCE_RECOVERY_OUTCOME_UNCERTAIN')
        _,cluster=identity_placement(row['settings'])
        if not archive and (type(cluster) is not int or cluster<=0):raise LifecycleError('RETIREMENT_BLOCKED')
        peers=connection.execute(sql.SQL("SELECT s.source_instance,s.settings FROM {} s WHERE s.source_instance<>%s AND NOT EXISTS(SELECT 1 FROM {} t WHERE t.source_instance=s.source_instance AND t.restored_at IS NULL) LIMIT 10001").format(
            self.store.table('sources'),self.store.table('source_tombstones')),(source,)).fetchall()
        if len(peers)>10000:raise LifecycleError('RETIREMENT_BLOCKED')
        for peer in peers:
            _,other_cluster=identity_placement(peer['settings'])
            if not archive and other_cluster==cluster:raise LifecycleError('RETIREMENT_BLOCKED')
        removed=connection.execute(sql.SQL('SELECT removed_at,restored_at FROM {} WHERE source_instance=%s').format(
            self.store.table('source_tombstones')),(source,)).fetchone()
        generation={key:value.isoformat() if value else None for key,value in removed.items()} if removed else None
        return row,cluster,generation

    def _record(self,connection,source,operation,actor):
        row=connection.execute(sql.SQL('SELECT * FROM {} WHERE operation_id=%s AND source_instance=%s').format(
            self.store.table('source_retirements')),(UUID(str(operation)),source)).fetchone()
        if row is None or row['actor_id']!=actor:raise LifecycleError('RETIREMENT_CONFLICT')
        return row

    def prepare(self,source,operation,actor,revision,guard_instance,remote):
        operation=UUID(str(operation));guard_instance=UUID(str(guard_instance))
        if not isinstance(actor,str) or not actor or len(actor)>200:raise LifecycleError('REQUEST_INVALID')
        if len(json.dumps(remote))>2*1024*1024:raise LifecycleError('RETIREMENT_BLOCKED')
        with self.store.connect() as connection,source_gate(
                connection,self.store.schema,source,allow_retirement=True):
            row,cluster,generation=self._guard(connection,source,revision,archive=remote.get('manifest',{}).get('format')==4)
            if (remote.get('nonce')!=str(operation) or remote.get('source_instance')!=source
                    or remote.get('status')!='REVIEWED' or remote.get('manifest',{}).get('format') not in (2,4)
                    or (remote['manifest'].get('format')==2 and remote['manifest'].get('cluster_id')!=cluster)):
                raise LifecycleError('RETIREMENT_CONFLICT')
            plan={'remote':remote,'removal_generation':generation,'source_flags':{key:row[key] for key in ('enabled','sync_enabled')}}
            previous=connection.execute(sql.SQL('SELECT * FROM {} WHERE operation_id=%s').format(
                self.store.table('source_retirements')),(operation,)).fetchone()
            if previous:
                if (previous['source_instance'],previous['actor_id'],previous['revision'],previous['guard_instance'],previous['plan'])!=(source,actor,revision,guard_instance,plan):
                    raise LifecycleError('RETIREMENT_CONFLICT')
                return previous
            return connection.execute(sql.SQL('INSERT INTO {} (operation_id,source_instance,actor_id,revision,guard_instance,plan) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *').format(
                self.store.table('source_retirements')),(operation,source,actor,revision,guard_instance,Jsonb(plan))).fetchone()

    def begin(self,source,operation,actor,digest,confirmed_source,remove_credentials):
        if type(remove_credentials) is not bool:raise LifecycleError('REQUEST_INVALID')
        with self.store.connect() as connection,source_gate(
                connection,self.store.schema,source,allow_retirement=True):
            record=self._record(connection,source,operation,actor)
            if record.get('superseded_by') is not None:raise LifecycleError('SOURCE_ARCHIVE_REVIEW_REQUIRED')
            row,_,generation=self._guard(connection,source,record['revision'],record['plan']['source_flags'] if record['state'] in ('SENDING','UNCERTAIN','SUCCEEDED','BLOCKED') else None,archive=record['plan']['remote']['manifest'].get('format')==4)
            if (record['plan']['remote']['digest']!=digest or (record['state']!='SUCCEEDED' and generation!=record['plan']['removal_generation'])
                    or confirmed_source!=row['name']):raise LifecycleError('RETIREMENT_CONFLICT')
            if record['state']!='READY':
                if record['remove_credentials']!=remove_credentials:
                    # Explicit Admin consent can finish an older operation which
                    # requested retention. Never turn previously granted cleanup off.
                    if record['remove_credentials'] is not False or remove_credentials is not True or record['state'] not in ('SENDING','UNCERTAIN','SUCCEEDED'):
                        raise LifecycleError('RETIREMENT_CONFLICT')
                    record=connection.execute(sql.SQL('UPDATE {} SET remove_credentials=true WHERE operation_id=%s RETURNING *').format(self.store.table('source_retirements')),(record['operation_id'],)).fetchone()
                return record,False
            older=connection.execute(sql.SQL("SELECT state,receipt FROM {} WHERE source_instance=%s AND state IN ('SENDING','UNCERTAIN','SUCCEEDED')").format(self.store.table('source_retirements')),(source,)).fetchall()
            for previous in older:
                # A legacy committed outcome is retained verbatim. A separate
                # confirmed current-inventory archive may close its namespace.
                if not (record['plan']['remote']['manifest'].get('format')==4 and previous['state']=='SUCCEEDED' and previous['receipt'] and previous['receipt'].get('status')=='SUCCEEDED' and previous['receipt'].get('generation_closed') is not True):
                    raise LifecycleError('SOURCE_RETIREMENT_PENDING')
            if record['plan']['remote']['manifest'].get('format')==4:
                connection.execute(sql.SQL("UPDATE {} SET superseded_by=%s WHERE source_instance=%s AND state='SUCCEEDED' AND COALESCE(receipt->>'generation_closed','false')<>'true' AND superseded_by IS NULL").format(self.store.table('source_retirements')),(record['operation_id'],source))
            # PREPARED proves credential dispatch has not begun. Closing this
            # generation cancels only such attempts; CREDENTIALS_PENDING was
            # refused by _guard and is never assumed not to have written.
            connection.execute(sql.SQL("UPDATE {} SET state='ABANDONED',finished_at=clock_timestamp() WHERE source_instance=%s AND state='PREPARED'").format(self.store.table('source_recoveries')),(source,))
            connection.execute(sql.SQL('UPDATE {} SET enabled=false,sync_enabled=false WHERE source_instance=%s').format(
                self.store.table('sources')),(source,))
            record=connection.execute(sql.SQL("UPDATE {} SET state='SENDING',remove_credentials=%s WHERE operation_id=%s RETURNING *").format(
                self.store.table('source_retirements')),(remove_credentials,record['operation_id'])).fetchone()
            return record,True

    def resume_legacy_busy(self,source,operation,actor):
        """Repair only the old misclassified namespace-busy confirmed attempt.

        This grants no new consent and sends no write. The coordinator must next
        read the exact original remote intent/receipt before any continuation.
        """
        with self.store.connect() as connection,source_gate(connection,self.store.schema,source,allow_retirement=True):
            record=self._record(connection,source,operation,actor)
            if (record['state']!='BLOCKED' or record['safe_code']!='SOURCE_OPERATION_ACTIVE'
                    or record['remove_credentials'] is not True or record['receipt'] is not None
                    or record.get('superseded_by') is not None
                    or record['plan']['remote']['manifest'].get('format')!=2):
                raise LifecycleError('RETIREMENT_CONFLICT')
            self._guard(connection,source,record['revision'],record['plan']['source_flags'])
            if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND operation_id<>%s AND state IN ('SENDING','UNCERTAIN','SUCCEEDED')").format(self.store.table('source_retirements')),(source,record['operation_id'])).fetchone():
                raise LifecycleError('SOURCE_RETIREMENT_PENDING')
            connection.execute(sql.SQL("UPDATE {} SET state='UNCERTAIN',safe_code='RETIREMENT_SERVER_BUSY' WHERE operation_id=%s").format(self.store.table('source_retirements')),(record['operation_id'],))

    def uncertain(self,source,operation,actor,code='RETIREMENT_UNCERTAIN'):
        if code not in {'RETIREMENT_UNCERTAIN','RETIREMENT_SERVER_BUSY'}:raise LifecycleError('REQUEST_INVALID')
        with self.store.connect() as connection,source_gate(connection,self.store.schema,source,allow_retirement=True):
            record=self._record(connection,source,operation,actor)
            if record['state'] not in ('SENDING','UNCERTAIN'):raise LifecycleError('RETIREMENT_CONFLICT')
            connection.execute(sql.SQL("UPDATE {} SET state='UNCERTAIN',safe_code=%s WHERE operation_id=%s").format(
                self.store.table('source_retirements')),(code,record['operation_id']))

    def resolve(self,source,operation,actor,guard_instance,receipt):
        with self.store.connect() as connection,source_gate(connection,self.store.schema,source,allow_retirement=True):
            record=self._record(connection,source,operation,actor)
            expected=record['plan']['remote']
            if (str(record['guard_instance'])!=str(guard_instance) or receipt.get('nonce')!=str(record['operation_id'])
                    or receipt.get('source_instance')!=source or receipt.get('digest')!=expected['digest']
                    or receipt.get('manifest')!=expected['manifest'] or receipt.get('status')!='SUCCEEDED'
                    or not isinstance(receipt.get('deleted'),list)
                    or not isinstance(receipt.get('already_absent',[]),list)
                    or (receipt.get('already_absent') and receipt['deleted'])
                    or sorted(receipt['deleted']+receipt.get('already_absent',[]))!=(sorted(item[0] for item in expected['manifest']['objects']) if expected['manifest']['format']==2 else [])):
                raise LifecycleError('RETIREMENT_CONFLICT')
            if record['state'] in ('SUCCEEDED','FINALIZED'):
                if record['receipt']!=receipt:raise LifecycleError('RETIREMENT_CONFLICT')
                return record
            if record['state'] not in ('SENDING','UNCERTAIN'):raise LifecycleError('RETIREMENT_CONFLICT')
            return connection.execute(sql.SQL("UPDATE {} SET state='SUCCEEDED',receipt=%s,safe_code=NULL,finished_at=clock_timestamp() WHERE operation_id=%s RETURNING *").format(
                self.store.table('source_retirements')),(Jsonb(receipt),record['operation_id'])).fetchone()


    def blocked(self,source,operation,actor,code='RETIREMENT_BLOCKED'):
        if code not in DEFINITE_REFUSALS:raise LifecycleError('REQUEST_INVALID')
        with self.store.connect() as connection,source_gate(connection,self.store.schema,source,allow_retirement=True):
            record=self._record(connection,source,operation,actor)
            if record['state'] not in ('SENDING','UNCERTAIN'):raise LifecycleError('RETIREMENT_CONFLICT')
            connection.execute(sql.SQL("UPDATE {} SET state='BLOCKED',safe_code=%s WHERE operation_id=%s").format(
                self.store.table('source_retirements')),(code,record['operation_id']))

    def finalized(self,source,operation,actor):
        with self.store.connect() as connection,source_gate(connection,self.store.schema,source,allow_retirement=True):
            record=self._record(connection,source,operation,actor)
            if record['state'] not in ('SUCCEEDED','FINALIZED'):raise LifecycleError('RETIREMENT_CONFLICT')
            removed=connection.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s AND restored_at IS NULL').format(
                self.store.table('source_tombstones')),(source,)).fetchone()
            if not removed:raise LifecycleError('RETIREMENT_CONFLICT')
            from .source_archive import close_generation
            from .legacy_admission import admission_lock
            admission_lock(connection,self.store.schema)
            if record['plan']['remote']['manifest'].get('format')==2:
                if record.get('local_cleanup_verified') is not True:raise LifecycleError('SOURCE_CREDENTIAL_CLEANUP_PENDING')
                connection.execute(sql.SQL('SELECT {}(%s,%s,%s)').format(self.store.table('purge_retired_source')),
                    (source,record['operation_id'],actor))
                return
            close_generation(self.store,connection,record)
            connection.execute(sql.SQL("UPDATE {} SET state='FINALIZED',safe_code=NULL WHERE operation_id=%s").format(
                self.store.table('source_retirements')),(record['operation_id'],))
