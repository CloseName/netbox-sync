"""Audited legacy admission decisions; never proves old NetBox object ownership."""
from uuid import UUID
from psycopg import sql
from psycopg.types.json import Jsonb
from .host_registration import legacy_anchor, registration_anchor, esxi_anchor, HostRegistrationConflict
from .source_lifecycle import LifecycleError
from .source_operations import source_gate
from .run_gates import blocking_runs


def isolated(row):
    decision=(row.get('settings') or {}).get('legacy_admission',{})
    try: UUID(decision['operation_id'])
    except (KeyError,TypeError,ValueError): return False
    return (decision.get('state')=='ISOLATED_UNPROVED' and row.get('enabled') is False
            and row.get('sync_enabled') is False)


def resolved_for_admission(row):
    decision=(row.get('settings') or {}).get('legacy_admission',{})
    return isolated(row) or (isinstance(decision,dict) and decision.get('state')=='OBSERVED_ENDPOINT'
        and registration_anchor(row.get('settings')) is not None
        and row.get('enabled') is False and row.get('sync_enabled') is False)


def admission_lock(connection,schema,shared=False):
    function='pg_try_advisory_xact_lock_shared' if shared else 'pg_try_advisory_xact_lock'
    row=connection.execute('SELECT '+function+'(hashtextextended(%s,0)) AS locked',
        ('netbox-sync:'+schema+':legacy-admission',)).fetchone()
    if not (row['locked'] if isinstance(row,dict) else row[0]):
        raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')


class LegacyAdmission:
    def __init__(self,store):self.store=store

    def _row(self,connection,source):
        row=connection.execute(sql.SQL('SELECT s.*,t.removed_at,t.restored_at FROM {} s LEFT JOIN {} t ON t.source_instance=s.source_instance WHERE s.source_instance=%s').format(self.store.table('sources'),self.store.table('source_tombstones')),(source,)).fetchone()
        if row is None:raise LifecycleError('SOURCE_NOT_FOUND')
        if row['source_type']!='esxi':raise LifecycleError('SOURCE_IDENTITY_UNSUPPORTED')
        return row

    def describe(self,source):
        with self.store.connect() as connection:
            row=self._row(connection,source)
            removed=connection.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s AND restored_at IS NULL').format(self.store.table('source_tombstones')),(source,)).fetchone()
            return dict(source_instance=source,name=row['name'],address=row['address'],
                port=(row['settings'] or {}).get('api_port',443),verify_ssl=row['verify_ssl'],
                revision=self.store.revision(row),host_uuid=registration_anchor(row['settings']),
                state='REMOVED' if removed else 'ACTIVE' if row['enabled'] else 'DISABLED',
                isolated=isolated(row),site_slug=row['site_slug'],cluster_name=row['cluster_name'],
                decision=(row['settings'] or {}).get('legacy_admission'))

    def status(self,source,actor,operation):
        with self.store.connect() as connection:
            previous=connection.execute(sql.SQL('SELECT revision,proof FROM {} WHERE operation_id=%s AND source_instance=%s AND actor_id=%s').format(self.store.table('source_identity_verifications')),(UUID(str(operation)),source,actor)).fetchone()
            return dict(previous) if previous and previous['proof'].get('purpose')=='LEGACY_ADMISSION' else {}

    def confirm(self,source,actor,operation,revision,decision,reason,anchor=None):
        operation=UUID(str(operation))
        if (decision not in {'ISOLATE','OBSERVE'} or not isinstance(actor,str) or not 1<=len(actor)<=200
                or not isinstance(reason,str) or not 3<=len(reason.strip())<=500):
            raise LifecycleError('REQUEST_INVALID')
        if decision=='OBSERVE':
            try:anchor=esxi_anchor({'provider':'esxi','hosts':[{'id':anchor}]})
            except HostRegistrationConflict:raise LifecycleError('SOURCE_IDENTITY_UNPROVED') from None
        elif anchor is not None:raise LifecycleError('REQUEST_INVALID')
        proof=dict(purpose='LEGACY_ADMISSION',decision=decision,reason=reason.strip(),anchor=anchor)
        with self.store.lock(self.store.lock_path):
            with self.store.connect() as connection:
                admission_lock(connection,self.store.schema)
                with source_gate(connection,self.store.schema,source):
                    previous=connection.execute(sql.SQL('SELECT * FROM {} WHERE operation_id=%s').format(self.store.table('source_identity_verifications')),(operation,)).fetchone()
                    if previous:
                        if (previous['source_instance'],previous['actor_id'],previous['revision'],previous['proof'])!=(source,actor,revision,proof):
                            raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
                        return dict(status='RECORDED',source_instance=source,operation_id=str(operation),decision=decision)
                    row=self._row(connection,source)
                    if self.store.revision(row)!=revision:raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
                    if registration_anchor(row['settings']):raise LifecycleError('SOURCE_IDENTITY_CHANGED')
                    if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status='RUNNING'").format(self.store.table('source_operations')),(source,)).fetchone():
                        raise LifecycleError('SOURCE_OPERATION_ACTIVE')
                    if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status IN ('RUNNING','OUTCOME_UNCERTAIN','PARTIALLY_APPLIED')").format(blocking_runs(connection,self.store.schema)),(source,)).fetchone():
                        raise LifecycleError('SOURCE_APPLY_UNCONFIRMED')
                    if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND state IN ('PREPARED','CREDENTIALS_PENDING')").format(self.store.table('source_recoveries')),(source,)).fetchone():
                        raise LifecycleError('SOURCE_RECOVERY_ACTIVE')
                    settings=dict(row['settings'] or {})
                    if decision=='OBSERVE':
                        others=connection.execute(sql.SQL("SELECT source_instance,settings FROM {} WHERE source_type='esxi' AND source_instance<>%s").format(self.store.table('sources')),(source,)).fetchall()
                        if any(registration_anchor(other['settings'])==anchor for other in others):raise LifecycleError('SOURCE_IDENTITY_CONFLICT')
                        reserved=connection.execute(sql.SQL('SELECT source_instance FROM {} WHERE provider=%s AND anchor=%s').format(self.store.table('host_reservations')),('esxi',anchor)).fetchone()
                        if reserved and reserved['source_instance']!=source:raise LifecycleError('SOURCE_IDENTITY_CONFLICT')
                    settings['legacy_admission']=dict(state='ISOLATED_UNPROVED' if decision=='ISOLATE' else 'OBSERVED_ENDPOINT',operation_id=str(operation),observed_uuid=anchor,physical_identity_proved=False,object_ownership_proved=False)
                    connection.execute(sql.SQL('INSERT INTO {} (operation_id,source_instance,actor_id,revision,anchor,proof) VALUES (%s,%s,%s,%s,%s,%s)').format(self.store.table('source_identity_verifications')),(operation,source,actor,revision,anchor or 'UNPROVED',Jsonb(proof)))
                    # Quarantine is explicit and cannot be undone by a schedule edit.
                    connection.execute(sql.SQL('UPDATE {} SET settings=%s,enabled=%s,sync_enabled=false WHERE source_instance=%s').format(self.store.table('sources')),(Jsonb(settings),False,source))
                    connection.execute(sql.SQL("UPDATE {} SET status='STALE',result=NULL,safe_error_code='PLAN_STALE',updated_at=clock_timestamp() WHERE source_instance=%s AND operation_kind='PLAN' AND status='READY'").format(self.store.table('source_operations')),(source,))
                    return dict(status='RECORDED',source_instance=source,operation_id=str(operation),decision=decision)
