"""Durable recovery of the same source namespace; no NetBox mutations.

Called only by the lifecycle control worker with trusted probe/catalog evidence.
Neither credentials nor arbitrary filesystem paths are accepted here.
"""
import re
from uuid import UUID
from .run_gates import blocking_runs
from psycopg import sql
from psycopg.types.json import Jsonb
from .host_registration import legacy_anchor,identity_placement
from .source_lifecycle import LifecycleError
from .source_operations import source_gate


class Recovery:
    def __init__(self, store, remote=None):
        self.store=store
        self.remote=remote

    def inventory(self,source,operation):
        # Narrow Admin view for retained/orphan ownership reconciliation. Native
        # NetBox view/guard permissions apply; absence is never deletion consent.
        if self.remote is None:raise LifecycleError('RETIREMENT_UNAVAILABLE')
        operation=UUID(str(operation))
        with self.store.lock(self.store.lock_path):
            with self.store.connect() as connection:self._row(connection,source)
            return self.remote.call('audit',operation,source_instance=source)['result']

    def records(self,source):
        """Admin comparison of recorded identity, not a physical equality claim.

        Tombstones/reservations and run history are deliberately retained. The
        existing recovery review proves NetBox ownership separately before any
        activation; this method neither chooses a winner nor changes a reserve.
        """
        with self.store.connect() as connection:
            selected=self._row(connection,source)
            anchor=legacy_anchor(selected['settings'])
            rows=connection.execute(sql.SQL('SELECT s.*,t.removed_at,t.restored_at FROM {} s LEFT JOIN {} t USING(source_instance) WHERE s.source_type=%s ORDER BY s.source_instance LIMIT 10001').format(
                self.store.table('sources'),self.store.table('source_tombstones')),(selected['source_type'],)).fetchall()
            if len(rows)>10000:raise LifecycleError('SOURCE_RECOVERY_IDENTITY_REVIEW')
            matching=[row for row in rows if row['source_instance']==source or anchor and legacy_anchor(row['settings'])==anchor]
            if len(matching)>100:raise LifecycleError('SOURCE_RECOVERY_IDENTITY_REVIEW')
            result=[]
            for row in matching:
                identifier=row['source_instance']
                runs=connection.execute(sql.SQL('SELECT run_id,status,started_at,finished_at FROM {} WHERE source_instance=%s ORDER BY started_at DESC LIMIT 5').format(self.store.table('sync_runs')),(identifier,)).fetchall()
                operations=connection.execute(sql.SQL("SELECT operation_id,operation_kind,status FROM {} WHERE source_instance=%s AND status='RUNNING' ORDER BY operation_id LIMIT 100").format(self.store.table('source_operations')),(identifier,)).fetchall()
                unresolved=connection.execute(sql.SQL("SELECT count(*) AS count FROM {} WHERE source_instance=%s AND status IN ('RUNNING','OUTCOME_UNCERTAIN','PARTIALLY_APPLIED')").format(blocking_runs(connection,self.store.schema)),(identifier,)).fetchone()['count']
                site,cluster=identity_placement(row['settings'])
                result.append(dict(source_instance=identifier,name=row['name'],address=row['address'],
                    host_uuid=legacy_anchor(row['settings']),site_id=site,cluster_id=cluster,
                    state='REMOVED' if row['removed_at'] and not row['restored_at'] else 'REGISTERED',
                    enabled=row['enabled'],schedule_enabled=row['sync_enabled'],unresolved_runs=unresolved,
                    removed_at=row['removed_at'].isoformat() if row['removed_at'] else None,
                    runs=[{**run,'run_id':str(run['run_id']),'started_at':run['started_at'].isoformat(),
                           'finished_at':run['finished_at'].isoformat() if run['finished_at'] else None} for run in runs],
                    operations=[{**op,'operation_id':str(op['operation_id'])} for op in operations]))
            return dict(sources=result,comparison='RECORDED_IDENTITY_ONLY',history_retained=True)

    def describe(self, source, actor):
        with self.store.connect() as connection,source_gate(connection,self.store.schema,source):
            row=self._row(connection,source)
            removed=connection.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s AND restored_at IS NULL').format(
                self.store.table('source_tombstones')), (source,)).fetchone()
            if not removed:raise LifecycleError('SOURCE_RECOVERY_NOT_REMOVED')
            site,cluster=identity_placement(row['settings'])
            if row['source_type']!='esxi' or any(type(v) is not int or v<=0 for v in (site,cluster)):
                raise LifecycleError('SOURCE_RECOVERY_IDENTITY_REVIEW')
            pending=connection.execute(sql.SQL("SELECT operation_id FROM {} WHERE source_instance=%s AND actor_id=%s AND state IN ('PREPARED','CREDENTIALS_PENDING')").format(
                self.store.table('source_recoveries')), (source,actor)).fetchone()
            return {'source_instance':source,'name':row['name'],'revision':self.store.revision(row),
                    'pending_operation':str(pending['operation_id']) if pending else None,
                    'host_uuid':legacy_anchor(row['settings']),'site_id':site,'cluster_id':cluster,
                    'completed_retirement':self._retired(connection,source) is not None}

    def _retired(self, connection, source):
        return connection.execute(sql.SQL("SELECT r.* FROM {} r JOIN {} t ON t.source_instance=r.source_instance WHERE r.source_instance=%s AND r.state='FINALIZED' AND t.restored_at IS NULL AND r.finished_at IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {} c WHERE c.source_instance=r.source_instance AND c.state='RESTORED' AND c.finished_at>=r.finished_at) ORDER BY r.finished_at DESC LIMIT 1").format(
            self.store.table('source_retirements'),self.store.table('source_tombstones'),self.store.table('source_recoveries')),(source,)).fetchone()

    def retired_evidence(self, source, operation):
        """Confirm an already completed retirement before restoring its namespace.

        Placement is repaired separately with fresh provider evidence; absence of
        a cluster cannot be interpreted as a new registration or new ownership.
        """
        from .netbox_catalog import fingerprint
        if self.remote is None:raise LifecycleError('RETIREMENT_UNAVAILABLE')
        with self.store.lock(self.store.lock_path):
            with self.store.connect() as connection,source_gate(connection,self.store.schema,source):
                row=self._row(connection,source);retired=self._retired(connection,source)
                if retired is None:raise LifecycleError('SOURCE_RECOVERY_IDENTITY_REVIEW')
                site,cluster=identity_placement(row['settings'])
            receipt=self.remote.call('receipt',retired['operation_id'])
            if (str(receipt['guard_instance'])!=str(retired['guard_instance']) or receipt['result']!=retired['receipt']
                    or receipt['result'].get('status')!='SUCCEEDED'):
                raise LifecycleError('SOURCE_RECOVERY_EVIDENCE_CHANGED')
            observed=self.remote.call('audit',operation,source_instance=source)
            if str(observed['guard_instance'])!=str(retired['guard_instance']):
                raise LifecycleError('SOURCE_RECOVERY_EVIDENCE_CHANGED')
            objects=observed['result']['objects']
            result=dict(source_instance=source,host_uuid=legacy_anchor(row['settings']),site_id=site,cluster_id=cluster,
                mode='RETIRED_EMPTY',retirement_id=str(retired['operation_id']),guard_instance=str(retired['guard_instance']),
                owned=[],retained_manual=[],blockers=['RETIRED_OBJECTS_PRESENT'] if any(item['present'] for item in objects) else [],
                inventory_digest=observed['result']['digest'],placement_requires_review=True)
            result['digest']=fingerprint(result)
            return result

    def _row(self, connection, source):
        row=connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s').format(
            self.store.table('sources')), (source,)).fetchone()
        if not row:raise LifecycleError('SOURCE_NOT_FOUND')
        return row

    def _guard(self, connection, row, revision, proof):
        source=row['source_instance']
        if self.store.revision(row)!=revision:raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
        removed=connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s AND restored_at IS NULL').format(
            self.store.table('source_tombstones')), (source,)).fetchone()
        if not removed or row['enabled']:raise LifecycleError('SOURCE_RECOVERY_NOT_REMOVED')
        if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status='RUNNING'").format(
                self.store.table('source_operations')), (source,)).fetchone():
            raise LifecycleError('SOURCE_OPERATION_ACTIVE')
        if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status IN ('RUNNING','OUTCOME_UNCERTAIN','PARTIALLY_APPLIED')").format(
                blocking_runs(connection,self.store.schema)), (source,)).fetchone():
            raise LifecycleError('SOURCE_APPLY_UNCONFIRMED')
        site,cluster=identity_placement(row['settings'])
        anchor=legacy_anchor(row['settings'])
        if (row['source_type']!='esxi' or not anchor or not isinstance(proof,dict)
                or proof.get('source_instance')!=source or proof.get('host_uuid')!=anchor
                or proof.get('blockers')!=[] or not re.fullmatch('[a-f0-9]{64}',proof.get('digest',''))
                or proof.get('site_id')!=site
                or proof.get('cluster_id')!=cluster):
            raise LifecycleError('SOURCE_RECOVERY_IDENTITY_REVIEW')
        if proof.get('mode')=='RETIRED_EMPTY':
            retired=self._retired(connection,source)
            if (retired is None or proof.get('retirement_id')!=str(retired['operation_id'])
                    or proof.get('guard_instance')!=str(retired['guard_instance'])
                    or proof.get('owned')!=[] or proof.get('retained_manual')!=[]):
                raise LifecycleError('SOURCE_RECOVERY_EVIDENCE_CHANGED')
        others=connection.execute(sql.SQL("SELECT settings FROM {} s WHERE source_type='esxi' AND source_instance<>%s AND NOT EXISTS (SELECT 1 FROM {} t WHERE t.source_instance=s.source_instance AND t.restored_at IS NULL)").format(
            self.store.table('sources'),self.store.table('source_tombstones')), (source,)).fetchall()
        if any(legacy_anchor(other['settings']) in (None,anchor) for other in others):
            raise LifecycleError('SOURCE_RECOVERY_IDENTITY_CONFLICT')
        return removed

    def prepare(self, source, operation, actor, revision, proof):
        operation=UUID(str(operation))
        if not isinstance(actor,str) or not actor or len(actor)>200:raise LifecycleError('REQUEST_INVALID')
        with self.store.lock(self.store.lock_path):
            with self.store.connect() as connection,source_gate(connection,self.store.schema,source):
                previous=connection.execute(sql.SQL('SELECT * FROM {} WHERE operation_id=%s').format(
                    self.store.table('source_recoveries')), (operation,)).fetchone()
                if previous:
                    if (previous['source_instance'],previous['actor_id'],previous['revision'],previous['plan']['proof'])!=(source,actor,revision,proof):
                        raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
                    return self._result(previous)
                row=self._row(connection,source)
                removed=self._guard(connection,row,revision,proof)
                if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND state IN ('PREPARED','CREDENTIALS_PENDING')").format(
                        self.store.table('source_recoveries')), (source,)).fetchone():
                    raise LifecycleError('SOURCE_RECOVERY_ACTIVE')
                plan={'proof':proof,'removal':{**removed,'removed_at':removed['removed_at'].isoformat()},
                      'credential_key':'src-recovery-'+operation.hex,
                      'broker_operation':operation.hex,
                      'previous_credentials':{k:row[k] for k in ('token_id_provider','token_id_key','token_secret_provider','token_secret_key')}}
                record=connection.execute(sql.SQL('INSERT INTO {} (operation_id,source_instance,actor_id,revision,plan) VALUES (%s,%s,%s,%s,%s) RETURNING *').format(
                    self.store.table('source_recoveries')), (operation,source,actor,revision,Jsonb(plan))).fetchone()
                return self._result(record)

    @staticmethod
    def _result(record):
        # Internal worker RPC only. API must project a public DTO without keys.
        return {'operation_id':str(record['operation_id']),'source_instance':record['source_instance'],
                'state':record['state'],'plan':record['plan']}

    def begin_credentials(self, source, operation, actor):
        with self.store.lock(self.store.lock_path):
            with self.store.connect() as connection,source_gate(connection,self.store.schema,source):
                record=self._attempt(connection,source,operation,actor)
                if record['state']=='RESTORED':return self._result(record)
                if record['state'] not in ('PREPARED','CREDENTIALS_PENDING'):raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
                self._guard(connection,self._row(connection,source),record['revision'],record['plan']['proof'])
                connection.execute(sql.SQL("UPDATE {} SET state='CREDENTIALS_PENDING' WHERE operation_id=%s").format(
                    self.store.table('source_recoveries')), (UUID(str(operation)),))
                record['state']='CREDENTIALS_PENDING'
                return self._result(record)

    def _attempt(self, connection, source, operation, actor):
        record=connection.execute(sql.SQL('SELECT * FROM {} WHERE operation_id=%s AND source_instance=%s AND actor_id=%s').format(
            self.store.table('source_recoveries')), (UUID(str(operation)),source,actor)).fetchone()
        if not record:raise LifecycleError('SOURCE_RECOVERY_NOT_FOUND')
        return record


    def complete(self, source, operation, actor, proof, metadata, verify_owned):
        """Commit only after fresh read evidence and broker ownership verification.

        metadata comes from an authenticated probe receipt, not user JSON. Secret
        contents never enter the lifecycle process, database or return value.
        """
        from dataclasses import replace
        from .source_config import SourceCredentials,SecretReference,source_port
        from .source_registry import SourceRegistry
        if (not isinstance(metadata,dict) or set(metadata)!={'username','address','verify_ssl','port'}
                or not isinstance(metadata['username'],str) or not metadata['username']
                or type(metadata['verify_ssl']) is not bool):raise LifecycleError('REQUEST_INVALID')
        source_port('esxi',metadata['port'])
        with self.store.lock(self.store.lock_path):
            with self.store.connect() as connection,source_gate(connection,self.store.schema,source):
                connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                    (f'netbox-sync:{self.store.schema}:credential-refs',))
                record=self._attempt(connection,source,operation,actor)
                if record['state']=='RESTORED':return self._result(record)
                if record['state']!='CREDENTIALS_PENDING':raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
                if proof!=record['plan']['proof']:raise LifecycleError('SOURCE_RECOVERY_EVIDENCE_CHANGED')
                row=self._row(connection,source)
                self._guard(connection,row,record['revision'],proof)
                key=record['plan']['credential_key']
                if verify_owned(key,record['plan']['broker_operation']) is not True:
                    raise LifecycleError('SOURCE_RECOVERY_CREDENTIALS_UNCONFIRMED')
                config=SourceRegistry._row_to_record(row).config
                config=replace(config,enabled=True,sync_enabled=False,address=metadata['address'],
                    verify_ssl=metadata['verify_ssl'],settings={**config.settings,'api_port':metadata['port'] or 443},
                    credentials=SourceCredentials(username=metadata['username'],
                        token_id=SecretReference(provider='file',key=key),
                        token_secret=SecretReference(provider='file',key=key)))
                SourceRegistry._validate_config(config)
                connection.execute(sql.SQL("UPDATE {} SET enabled=true,sync_enabled=false,address=%s,verify_ssl=%s,username=%s,"
                    "token_id_provider='file',token_id_key=%s,token_secret_provider='file',token_secret_key=%s,settings=%s WHERE source_instance=%s").format(
                    self.store.table('sources')), (config.address,config.verify_ssl,metadata['username'],key,key,Jsonb(dict(config.settings)),source))
                connection.execute(sql.SQL('UPDATE {} SET restored_at=clock_timestamp() WHERE source_instance=%s AND restored_at IS NULL').format(
                    self.store.table('source_tombstones')), (source,))
                connection.execute(sql.SQL("UPDATE {} SET status='STALE',result=NULL,safe_error_code='PLAN_STALE',updated_at=clock_timestamp() "
                    "WHERE source_instance=%s AND operation_kind='PLAN' AND status='READY'").format(
                    self.store.table('source_operations')), (source,))
                connection.execute(sql.SQL("UPDATE {} SET state='RESTORED',finished_at=clock_timestamp() WHERE operation_id=%s").format(
                    self.store.table('source_recoveries')), (UUID(str(operation)),))
                record['state']='RESTORED'
                return self._result(record)

    def status(self, source, operation, actor):
        with self.store.connect() as connection,source_gate(connection,self.store.schema,source):
            record=self._attempt(connection,source,operation,actor)
            row=self._row(connection,source)
            return {'state':record['state'],'source_instance':source,'enabled':bool(row['enabled'])}

    def abandon_prepared(self, source, operation, actor):
        """Only a durable pre-credential attempt can be abandoned automatically."""
        with self.store.lock(self.store.lock_path):
            with self.store.connect() as connection,source_gate(connection,self.store.schema,source):
                record=self._attempt(connection,source,operation,actor)
                if record['state']=='ABANDONED':return self._result(record)
                if record['state']!='PREPARED':raise LifecycleError('SOURCE_RECOVERY_OUTCOME_UNCERTAIN')
                connection.execute(sql.SQL("UPDATE {} SET state='ABANDONED',finished_at=clock_timestamp() WHERE operation_id=%s").format(
                    self.store.table('source_recoveries')), (UUID(str(operation)),))
                record['state']='ABANDONED'
                return self._result(record)
