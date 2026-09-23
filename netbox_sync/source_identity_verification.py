"""Verify legacy hardware identity from fresh discovery and existing provenance.

No object adoption, source activation, address change or credential operation.
"""
from uuid import UUID
from psycopg import sql
from psycopg.types.json import Jsonb
from .host_registration import legacy_anchor,esxi_anchor,HostRegistrationConflict
from .source_lifecycle import LifecycleError
from .source_operations import source_gate
from .placement_control import row as active_row
from .api.dto import DiscoveryHostDTO


class IdentityVerification:
    def __init__(self,store):self.store=store

    def _evidence(self,connection,source):
        operation=connection.execute(sql.SQL("SELECT operation_id,result,finished_at FROM {} WHERE source_instance=%s AND operation_kind='DISCOVERY' AND status='SUCCEEDED' AND finished_at>clock_timestamp()-interval '10 minutes'").format(self.store.table('source_operations')),(source,)).fetchone()
        try:
            if operation['result']['source_instance']!=source:raise ValueError()
            hosts=[DiscoveryHostDTO.model_validate(item).model_dump() for item in operation['result']['hosts']]
            anchor=esxi_anchor({'provider':'esxi','hosts':hosts})
        except (TypeError,KeyError,ValueError,HostRegistrationConflict):
            raise LifecycleError('SOURCE_DISCOVERY_REQUIRED') from None
        return str(operation['operation_id']),anchor,operation['finished_at'].isoformat()

    def _describe(self,connection,source):
        row=active_row(self.store,connection,source)
        if row['source_type']!='esxi':raise LifecycleError('SOURCE_IDENTITY_UNSUPPORTED')
        discovery,anchor,observed_at=self._evidence(connection,source)
        recorded=legacy_anchor(row['settings'])
        return row,{'source_instance':source,'revision':self.store.revision(row),'discovery_id':discovery,
                    'host_uuid':anchor,'recorded_uuid':recorded,'observed_at':observed_at,
                    'site_slug':row['site_slug'],'cluster_name':row['cluster_name']}

    def describe(self,source):
        with self.store.connect() as connection,source_gate(connection,self.store.schema,source):
            return self._describe(connection,source)[1]

    def confirm(self,source,actor,revision,discovery_id,proof):
        operation=UUID(str(discovery_id))
        if not isinstance(actor,str) or not actor or len(actor)>200:raise LifecycleError('REQUEST_INVALID')
        with self.store.lock(self.store.lock_path):
            with self.store.connect() as connection,source_gate(connection,self.store.schema,source):
                previous=connection.execute(sql.SQL('SELECT * FROM {} WHERE operation_id=%s').format(
                    self.store.table('source_identity_verifications')),(operation,)).fetchone()
                if previous:
                    if (previous['source_instance'],previous['actor_id'],previous['revision'],previous['proof'])!=(source,actor,revision,proof):
                        raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
                    return {'status':'VERIFIED','source_instance':source,'host_uuid':previous['anchor']}
                row,meta=self._describe(connection,source)
                if meta['recorded_uuid'] and meta['recorded_uuid']!=meta['host_uuid']:
                    raise LifecycleError('SOURCE_IDENTITY_CHANGED')
                if (meta['revision'],meta['discovery_id'])!=(revision,str(operation)):
                    raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
                if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status='RUNNING'").format(self.store.table('source_operations')),(source,)).fetchone():
                    raise LifecycleError('SOURCE_OPERATION_ACTIVE')
                if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status IN ('RUNNING','OUTCOME_UNCERTAIN','PARTIALLY_APPLIED')").format(self.store.table('sync_runs')),(source,)).fetchone():
                    raise LifecycleError('SOURCE_APPLY_UNCONFIRMED')
                if (not isinstance(proof,dict) or proof.get('source_instance')!=source
                    or proof.get('host_uuid')!=meta['host_uuid'] or proof.get('blockers')!=[]
                    or proof.get('configured_target')!={'site_slug':meta['site_slug'],'cluster_name':meta['cluster_name']}
                    or any(type(proof.get(k)) is not int or proof[k]<=0 for k in ('site_id','cluster_id'))
                    or len([item for item in proof.get('owned',[]) if item.get('kind')=='device'])!=1):
                    raise LifecycleError('SOURCE_IDENTITY_UNPROVED')
                others=connection.execute(sql.SQL("SELECT settings FROM {} WHERE source_type='esxi' AND source_instance<>%s").format(self.store.table('sources')),(source,)).fetchall()
                if any(legacy_anchor(other['settings'])==meta['host_uuid'] for other in others):
                    raise LifecycleError('SOURCE_IDENTITY_CONFLICT')
                identity={'version':1,'provider':'esxi','hardware_uuid':meta['host_uuid'],
                          'verification_id':str(operation),'site_id':proof['site_id'],'cluster_id':proof['cluster_id']}
                connection.execute(sql.SQL('INSERT INTO {} (operation_id,source_instance,actor_id,revision,anchor,proof) VALUES (%s,%s,%s,%s,%s,%s)').format(self.store.table('source_identity_verifications')),
                    (operation,source,actor,revision,meta['host_uuid'],Jsonb(proof)))
                connection.execute(sql.SQL("UPDATE {} SET settings=jsonb_set(COALESCE(settings,'{{}}'::jsonb),'{{provider_identity}}',%s) WHERE source_instance=%s").format(self.store.table('sources')),(Jsonb(identity),source))
                connection.execute(sql.SQL("UPDATE {} SET status='STALE',result=NULL,safe_error_code='PLAN_STALE',updated_at=clock_timestamp() WHERE source_instance=%s AND operation_kind='PLAN' AND status='READY'").format(self.store.table('source_operations')),(source,))
                return {'status':'VERIFIED','source_instance':source,'host_uuid':meta['host_uuid']}
