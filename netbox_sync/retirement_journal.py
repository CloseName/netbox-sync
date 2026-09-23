"""DB-only lifecycle journal. No NetBox token, HTTP client or secret filesystem.

The trusted coordinator supplies checked guard evidence. This module does
not itself perform retirement, activate old tombstones or authorize API callers.
"""
import json
from uuid import UUID
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

    def _guard(self,connection,source,revision,pending_flags=None):
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
                self.store.table('sync_runs')),(source,)).fetchone():
            raise LifecycleError('SOURCE_APPLY_UNCONFIRMED')
        _,cluster=identity_placement(row['settings'])
        if type(cluster) is not int or cluster<=0:raise LifecycleError('RETIREMENT_BLOCKED')
        peers=connection.execute(sql.SQL("SELECT s.source_instance,s.settings FROM {} s WHERE s.source_instance<>%s AND NOT EXISTS(SELECT 1 FROM {} t WHERE t.source_instance=s.source_instance AND t.restored_at IS NULL) LIMIT 10001").format(
            self.store.table('sources'),self.store.table('source_tombstones')),(source,)).fetchall()
        if len(peers)>10000:raise LifecycleError('RETIREMENT_BLOCKED')
        for peer in peers:
            _,other_cluster=identity_placement(peer['settings'])
            if other_cluster is None or other_cluster==cluster:raise LifecycleError('RETIREMENT_BLOCKED')
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
            row,cluster,generation=self._guard(connection,source,revision)
            if (remote.get('nonce')!=str(operation) or remote.get('source_instance')!=source
                    or remote.get('status')!='REVIEWED' or remote.get('manifest',{}).get('format')!=2
                    or remote['manifest'].get('cluster_id')!=cluster):
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
            row,_,generation=self._guard(connection,source,record['revision'],record['plan']['source_flags'] if record['state'] in ('SENDING','UNCERTAIN','SUCCEEDED','BLOCKED') else None)
            if (record['plan']['remote']['digest']!=digest or generation!=record['plan']['removal_generation']
                    or confirmed_source!=row['name']):raise LifecycleError('RETIREMENT_CONFLICT')
            if record['state']!='READY':
                if record['remove_credentials']!=remove_credentials:raise LifecycleError('RETIREMENT_CONFLICT')
                return record,False
            if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND state IN ('SENDING','UNCERTAIN','SUCCEEDED')").format(
                    self.store.table('source_retirements')),(source,)).fetchone():raise LifecycleError('SOURCE_RETIREMENT_PENDING')
            connection.execute(sql.SQL('UPDATE {} SET enabled=false,sync_enabled=false WHERE source_instance=%s').format(
                self.store.table('sources')),(source,))
            record=connection.execute(sql.SQL("UPDATE {} SET state='SENDING',remove_credentials=%s WHERE operation_id=%s RETURNING *").format(
                self.store.table('source_retirements')),(remove_credentials,record['operation_id'])).fetchone()
            return record,True

    def uncertain(self,source,operation,actor):
        with self.store.connect() as connection,source_gate(connection,self.store.schema,source,allow_retirement=True):
            record=self._record(connection,source,operation,actor)
            if record['state'] not in ('SENDING','UNCERTAIN'):raise LifecycleError('RETIREMENT_CONFLICT')
            connection.execute(sql.SQL("UPDATE {} SET state='UNCERTAIN',safe_code='RETIREMENT_UNCERTAIN' WHERE operation_id=%s").format(
                self.store.table('source_retirements')),(record['operation_id'],))

    def resolve(self,source,operation,actor,guard_instance,receipt):
        with self.store.connect() as connection,source_gate(connection,self.store.schema,source,allow_retirement=True):
            record=self._record(connection,source,operation,actor)
            expected=record['plan']['remote']
            if (str(record['guard_instance'])!=str(guard_instance) or receipt.get('nonce')!=str(record['operation_id'])
                    or receipt.get('source_instance')!=source or receipt.get('digest')!=expected['digest']
                    or receipt.get('manifest')!=expected['manifest'] or receipt.get('status')!='SUCCEEDED'
                    or not isinstance(receipt.get('deleted'),list)
                    or sorted(receipt['deleted'])!=sorted(item[0] for item in expected['manifest']['objects'])):
                raise LifecycleError('RETIREMENT_CONFLICT')
            if record['state'] in ('SUCCEEDED','FINALIZED'):
                if record['receipt']!=receipt:raise LifecycleError('RETIREMENT_CONFLICT')
                return record
            if record['state'] not in ('SENDING','UNCERTAIN'):raise LifecycleError('RETIREMENT_CONFLICT')
            return connection.execute(sql.SQL("UPDATE {} SET state='SUCCEEDED',receipt=%s,safe_code=NULL,finished_at=clock_timestamp() WHERE operation_id=%s RETURNING *").format(
                self.store.table('source_retirements')),(Jsonb(receipt),record['operation_id'])).fetchone()


    def blocked(self,source,operation,actor):
        with self.store.connect() as connection,source_gate(connection,self.store.schema,source,allow_retirement=True):
            record=self._record(connection,source,operation,actor)
            if record['state'] not in ('SENDING','UNCERTAIN'):raise LifecycleError('RETIREMENT_CONFLICT')
            connection.execute(sql.SQL("UPDATE {} SET state='BLOCKED',safe_code='RETIREMENT_BLOCKED' WHERE operation_id=%s").format(
                self.store.table('source_retirements')),(record['operation_id'],))

    def finalized(self,source,operation,actor):
        with self.store.connect() as connection,source_gate(connection,self.store.schema,source,allow_retirement=True):
            record=self._record(connection,source,operation,actor)
            if record['state'] not in ('SUCCEEDED','FINALIZED'):raise LifecycleError('RETIREMENT_CONFLICT')
            removed=connection.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s AND restored_at IS NULL').format(
                self.store.table('source_tombstones')),(source,)).fetchone()
            if not removed:raise LifecycleError('RETIREMENT_CONFLICT')
            connection.execute(sql.SQL("UPDATE {} SET state='FINALIZED' WHERE operation_id=%s").format(
                self.store.table('source_retirements')),(record['operation_id'],))
