"""Narrow lifecycle capability for reviewed placement; no NetBox or secret access."""
from psycopg import sql
from psycopg.types.json import Jsonb
from .source_lifecycle import LifecycleError
from .source_operations import source_gate
from .api.dto import DiscoveryHostDTO
from .netbox_catalog import project

KINDS={'site','cluster','platform','device_role','cluster_type'}


def row(store,connection,source):
    value=connection.execute(sql.SQL('SELECT * FROM {} WHERE source_instance=%s').format(store.table('sources')),(source,)).fetchone()
    if not value or connection.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s AND restored_at IS NULL').format(store.table('source_tombstones')),(source,)).fetchone():
        raise LifecycleError('SOURCE_NOT_FOUND')
    return value


def evidence(store,connection,source):
    operation=connection.execute(sql.SQL("SELECT operation_id,result FROM {} WHERE source_instance=%s AND operation_kind='DISCOVERY' AND status='SUCCEEDED' AND finished_at>clock_timestamp()-interval '24 hours' ORDER BY finished_at DESC, operation_id DESC LIMIT 1").format(store.table('source_operations')),(source,)).fetchone()
    try:
        hosts=[DiscoveryHostDTO.model_validate(item).model_dump() for item in operation['result']['hosts']]
        if not 1<=len(hosts)<=16 or len({h['id'] for h in hosts})!=len(hosts):raise ValueError()
        return str(operation['operation_id']),hosts
    except (TypeError,KeyError,ValueError):raise LifecycleError('SOURCE_DISCOVERY_REQUIRED') from None


def choice(kind,value):
    # Return only the same bounded projection used by the catalog API.
    result=project(kind,{**value,**({'model':value.get('name')} if kind=='device_type' else {})})
    if result['fingerprint']!=value.get('fingerprint'):raise LifecycleError('REQUEST_INVALID')
    return result


def read(store,source):
    with store.connect() as connection,source_gate(connection,store.schema,source):
        current=row(store,connection,source);identifier,hosts=evidence(store,connection,source)
        mapping=(current['settings'] or {}).get('onboarding_mapping',{})
        refs={kind:choice(kind,value) for kind,value in mapping.get('references',{}).items() if kind in KINDS}
        types={host['id']:choice('device_type',mapping['host_types'][host['id']]) for host in hosts if host['id'] in mapping.get('host_types',{})}
        return dict(source_instance=source,revision=store.revision(current),discovery_id=identifier,
                    preview=dict(provider=current['source_type'],name=hosts[0]['name'] if len(hosts)==1 else None,cluster=None,hosts=hosts),
                    references=refs,host_types=types,ip_conflict_policy=mapping.get('ip_conflict_policy','strict'))


def save(store,source,revision,discovery_id,mapping):
    with store.lock(store.lock_path):
        with store.connect() as connection,source_gate(connection,store.schema,source):
            current=row(store,connection,source)
            if store.revision(current)!=revision:raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
            if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status='RUNNING'").format(store.table('source_operations')),(source,)).fetchone():
                raise LifecycleError('SOURCE_OPERATION_ACTIVE')
            if connection.execute(sql.SQL("SELECT 1 FROM {} WHERE source_instance=%s AND status IN ('RUNNING','OUTCOME_UNCERTAIN','PARTIALLY_APPLIED')").format(store.table('sync_runs')),(source,)).fetchone():
                raise LifecycleError('SOURCE_APPLY_UNCONFIRMED')
            identifier,hosts=evidence(store,connection,source)
            if identifier!=discovery_id:raise LifecycleError('SOURCE_LIFECYCLE_CONFLICT')
            if (not isinstance(mapping,dict) or set(mapping)-{'ip_conflict_policy'}!={'version','references','host_types','hosts'}
                    or mapping['version']!=1 or mapping['hosts']!=hosts or set(mapping['references'])!=KINDS
                    or set(mapping['host_types'])!={h['id'] for h in hosts}):raise LifecycleError('REQUEST_INVALID')
            refs={kind:choice(kind,value) for kind,value in mapping['references'].items()}
            types={key:choice('device_type',value) for key,value in mapping['host_types'].items()}
            cluster=refs['cluster']
            if cluster['scope_type']!='dcim.site' or cluster['scope_id']!=refs['site']['id'] or (cluster['type'] or {}).get('id')!=refs['cluster_type']['id']:
                raise LifecycleError('REQUEST_INVALID')
            previous=(current['settings'] or {}).get('onboarding_mapping',{})
            policy = mapping.get('ip_conflict_policy', previous.get('ip_conflict_policy', 'strict'))
            if policy not in ('strict', 'observe'):raise LifecycleError('REQUEST_INVALID')
            # Retain mappings of absent hosts. Disappearance never removes identities.
            old_hosts=[h for h in previous.get('hosts',[]) if h['id'] not in types]
            retained=dict(version=1,ip_conflict_policy=policy,references=refs,host_types={**previous.get('host_types',{}),**types},hosts=old_hosts+hosts)
            connection.execute(sql.SQL("UPDATE {} SET site_slug=%s,cluster_name=%s,platform_slug=%s,device_role_slug=%s,cluster_type_slug=%s,device_type_slug=%s,settings=jsonb_set(COALESCE(settings,'{{}}'::jsonb),'{{onboarding_mapping}}',%s) WHERE source_instance=%s").format(store.table('sources')),
                (refs['site']['slug'],cluster['name'],refs['platform']['slug'],refs['device_role']['slug'],refs['cluster_type']['slug'],next(iter(types.values()))['slug'],Jsonb(retained),source))
            connection.execute(sql.SQL("UPDATE {} SET status='STALE',result=NULL,safe_error_code='PLAN_STALE',updated_at=clock_timestamp() WHERE source_instance=%s AND operation_kind='PLAN' AND status='READY'").format(store.table('source_operations')),(source,))
    return store.read(source)
