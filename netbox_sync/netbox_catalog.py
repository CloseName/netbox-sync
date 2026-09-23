"""Read-only bounded catalog RPC child. Destination comes only from protected state."""
import hashlib
import json
import sys
from urllib.parse import urlencode,urlsplit
import requests
from .api.egress import EgressPolicy,pinned_dns
from .bootstrap_probe import fetch,ProbeError
from .netbox_tls import configure_session

ENDPOINTS={'manufacturer':'dcim/manufacturers','site':'dcim/sites','cluster':'virtualization/clusters','platform':'dcim/platforms',
    'device_role':'dcim/device-roles','device_type':'dcim/device-types','cluster_type':'virtualization/cluster-types','vrf':'ipam/vrfs'}

def fingerprint(row):
    return hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def project(kind,row):
    if type(row.get('id')) is not int or row['id']<=0: raise ProbeError('RESPONSE_INVALID')
    def short(value): return value[:200] if isinstance(value,str) else ''
    def related(value):
        return {'id':value.get('id'),'name':short(value.get('name') or value.get('display'))} if isinstance(value,dict) else None
    value=dict(id=row['id'],name=short(row.get('model') if kind=='device_type' else row.get('name')),
        slug=short(row.get('slug')),manufacturer=related(row.get('manufacturer')),
        type=related(row.get('type')),scope_type=row.get('scope_type'),scope_id=row.get('scope_id'),
        site=related(row.get('site')),scope=related(row.get('scope')))
    if kind=='vrf':
        value=dict(id=row['id'],name=short(row.get('name')),rd=row.get('rd'),enforce_unique=row.get('enforce_unique',True))
        if value['rd'] is not None and (not isinstance(value['rd'],str) or len(value['rd'])>64):raise ProbeError('RESPONSE_INVALID')
        if type(value['enforce_unique']) is not bool:raise ProbeError('RESPONSE_INVALID')
    value['fingerprint']=fingerprint(value)
    return value

def query(value,session_factory=requests.Session):
    payload=value['query'];kind=payload.get('kind'); action=payload.get('action')
    parsed=urlsplit(value['url']);port=parsed.port or 443
    host,address=EgressPolicy(allowed_hosts=(parsed.hostname,)).resolve(parsed.hostname,port)
    with pinned_dns(host,address,port),session_factory() as session:
        configure_session(session)
        def get(kind,tail):
            return fetch(session,value['url']+'/api/'+ENDPOINTS[kind]+'/'+tail,value['read_token'])
        if action=='validate-scopes':
            from .network_scopes import rules,NetworkScopeError
            if set(payload)!={'action','rules'}:raise ProbeError('RESPONSE_INVALID')
            try:selected=rules(payload['rules'])
            except NetworkScopeError:raise ProbeError('RESPONSE_INVALID') from None
            for rule in selected:
                current=project('vrf',get('vrf',str(rule['vrf']['id'])+'/'))
                if current!=rule['vrf']:raise ProbeError('CATALOG_CHANGED')
            return {'rules':selected}
        if action in ('recovery-evidence','identity-evidence'):
            from .recovery_evidence import assess
            from .source_config import SOURCE_INSTANCE_PATTERN
            from .esxi_discovery import _validated_host_hardware_uuid
            expected={'action','source_instance','host_uuid'} | ({'site_slug','cluster_name'} if action=='identity-evidence' else {'site_id','cluster_id'})
            if (set(payload)!=expected
                    or not isinstance(payload['source_instance'],str)
                    or not SOURCE_INSTANCE_PATTERN.fullmatch(payload['source_instance'])
                    or not isinstance(payload['host_uuid'],str)
                    or _validated_host_hardware_uuid(payload['host_uuid'])!=payload['host_uuid']):
                raise ProbeError('RESPONSE_INVALID')
            def inventory(endpoint,filters=None):
                rows=[];total=None
                while True:
                    page=fetch(session,value['url']+'/api/'+endpoint+'/?'+urlencode(
                        dict(limit=100,offset=len(rows),ordering='id',**(filters or {}))),value['read_token'])
                    batch=page.get('results');count=page.get('count')
                    if (not isinstance(batch,list) or len(batch)>100 or type(count) is not int
                            or not 0<=count<=10000 or total is not None and count!=total):
                        raise ProbeError('RESPONSE_INVALID')
                    total=count;rows.extend(batch)
                    if len(rows)>total:raise ProbeError('RESPONSE_INVALID')
                    if len(rows)==total:
                        if page.get('next') is not None:raise ProbeError('RESPONSE_INVALID')
                        return rows
                    if not batch or page.get('next') is None:raise ProbeError('RESPONSE_INVALID')
                    # Never follow an API-provided URL with the read token.
            configured=None
            if action=='identity-evidence':
                if any(not isinstance(payload[k],str) or not payload[k] or len(payload[k])>200 for k in ('site_slug','cluster_name')):
                    raise ProbeError('RESPONSE_INVALID')
                configured={k:payload[k] for k in ('site_slug','cluster_name')}
                sites=[r for r in inventory('dcim/sites',{'slug':payload['site_slug']}) if r.get('slug')==payload['site_slug']]
                if len(sites)!=1:raise ProbeError('SELECTION_REQUIRED')
                site_id=sites[0].get('id')
                if type(site_id) is not int or site_id<=0:raise ProbeError('RESPONSE_INVALID')
                clusters=[r for r in inventory('virtualization/clusters',{'name':payload['cluster_name']})
                    if r.get('name')==payload['cluster_name'] and r.get('scope_type')=='dcim.site' and r.get('scope_id')==site_id]
                if len(clusters)!=1:raise ProbeError('SELECTION_REQUIRED')
                payload={**payload,'site_id':site_id,'cluster_id':clusters[0].get('id')}
            if any(type(payload[k]) is not int or payload[k]<=0 for k in ('site_id','cluster_id')):
                raise ProbeError('RESPONSE_INVALID')
            result=assess(payload['source_instance'],payload['host_uuid'],payload['site_id'],
                payload['cluster_id'],get('cluster',str(payload['cluster_id'])+'/'),
                inventory('dcim/devices'),inventory('virtualization/virtual-machines'),require_host=action=='identity-evidence')
            if configured:
                result['configured_target']=configured
                # Chain the inventory digest: object provenance may change while
                # the projected IDs and blockers remain identical.
                result['digest']=fingerprint(result)
            return result
        if action=='list':
            if kind not in ENDPOINTS: raise ProbeError('RESPONSE_INVALID')
            search=payload.get('search',''); offset=payload.get('offset',0)
            if not isinstance(search,str) or len(search)>100 or type(offset) is not int or not 0<=offset<=10000:
                raise ProbeError('RESPONSE_INVALID')
            result=get(kind,'?'+urlencode(dict(q=search,limit=20,offset=offset,ordering='id')))
            rows=result.get('results');count=result.get('count')
            if not isinstance(rows,list) or len(rows)>20 or type(count) is not int: raise ProbeError('RESPONSE_INVALID')
            return dict(items=[project(kind,r) for r in rows],count=count,offset=offset,
                more=result.get('next') is not None,url=value['url']+'/'+ENDPOINTS[kind]+'/')
        if action=='resolve-placement':
            from .placement_resolution import resolve
            def listing(kind,search):
                return get(kind,'?'+urlencode(dict(q=search,limit=20,ordering='id')))
            resolved=resolve(payload,listing,project)
            cluster=resolved['references'].get('cluster')
            if cluster:
                # Existing inventory is not proof of ownership by this new source.
                # Revival remains a separate Admin workflow; never adopt by name.
                for endpoint in ('dcim/devices','virtualization/virtual-machines'):
                    existing=fetch(session,value['url']+'/api/'+endpoint+'/?'+urlencode(dict(cluster_id=cluster['id'],limit=1)),value['read_token'])
                    if type(existing.get('count')) is not int:raise ProbeError('RESPONSE_INVALID')
                    if existing['count']:
                        resolved['issues'].append({'kind':'cluster','code':'OWNERSHIP_REVIEW_REQUIRED'})
                        break
            return resolved
        if action=='validate':
            selections=payload.get('selections')
            if not isinstance(selections,list) or not 5<=len(selections)<=21: raise ProbeError('RESPONSE_INVALID')
            result=[]
            for choice in selections:
                kind=choice.get('kind');identifier=choice.get('id')
                if kind not in ENDPOINTS or type(identifier) is not int or identifier<=0: raise ProbeError('RESPONSE_INVALID')
                fresh=project(kind,get(kind,str(identifier)+'/'))
                if fresh['fingerprint']!=choice.get('fingerprint'): raise ProbeError('CATALOG_CHANGED')
                result.append(dict(kind=kind,**fresh))
            if payload.get('empty_cluster_id') is not None:
                cluster_id=payload['empty_cluster_id']
                if type(cluster_id) is not int or cluster_id<=0:raise ProbeError('RESPONSE_INVALID')
                for endpoint in ('dcim/devices','virtualization/virtual-machines'):
                    existing=fetch(session,value['url']+'/api/'+endpoint+'/?'+urlencode(dict(cluster_id=cluster_id,limit=1)),value['read_token'])
                    if type(existing.get('count')) is not int:raise ProbeError('RESPONSE_INVALID')
                    if existing['count']:raise ProbeError('CLUSTER_REVIEW_REQUIRED')
            return {'selections':result}
        raise ProbeError('RESPONSE_INVALID')

def main():
    try:
        result=query(json.loads(sys.stdin.buffer.read(24577)))
        if len(json.dumps(result).encode())>24576: raise ProbeError('RESPONSE_INVALID')
    except requests.exceptions.SSLError: result={'error':'TLS_FAILED'}
    except (requests.exceptions.ConnectionError,requests.exceptions.Timeout): result={'error':'NETWORK_UNREACHABLE'}
    except ProbeError as error: result={'error':error.code}
    except Exception: result={'error':'RESPONSE_INVALID'}
    print(json.dumps(result))

if __name__=='__main__': main()
