"""Durable recovery of the same source namespace; no NetBox mutations.

Called only by the lifecycle control worker with trusted probe/catalog evidence.
Neither credentials nor arbitrary filesystem paths are accepted here.
"""
import re
from uuid import UUID
from psycopg import sql
from psycopg.types.json import Jsonb
from .host_registration import legacy_anchor,identity_placement
from .source_lifecycle import LifecycleError
from .source_operations import source_gate


class Recovery:
    def __init__(self, store):
        self.store=store

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
                    'host_uuid':legacy_anchor(row['settings']),'site_id':site,'cluster_id':cluster}

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
                self.store.table('sync_runs')), (source,)).fetchone():
            raise LifecycleError('SOURCE_APPLY_UNCONFIRMED')
        site,cluster=identity_placement(row['settings'])
        anchor=legacy_anchor(row['settings'])
        if (row['source_type']!='esxi' or not anchor or not isinstance(proof,dict)
                or proof.get('source_instance')!=source or proof.get('host_uuid')!=anchor
                or proof.get('blockers')!=[] or not re.fullmatch('[a-f0-9]{64}',proof.get('digest',''))
                or proof.get('site_id')!=site
                or proof.get('cluster_id')!=cluster):
            raise LifecycleError('SOURCE_RECOVERY_IDENTITY_REVIEW')
        others=connection.execute(sql.SQL("SELECT settings FROM {} WHERE source_type='esxi' AND enabled=true AND source_instance<>%s").format(
            self.store.table('sources')), (source,)).fetchall()
        if any(legacy_anchor(other['settings'])==anchor for other in others):
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
