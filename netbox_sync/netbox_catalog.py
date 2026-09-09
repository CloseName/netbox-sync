"""Read-only bounded catalog RPC child. Destination comes only from protected state."""
import hashlib
import json
import sys
from urllib.parse import urlencode,urlsplit
import requests
from .api.egress import EgressPolicy,pinned_dns
from .bootstrap_probe import fetch,ProbeError
from .netbox_tls import configure_session

ENDPOINTS={'site':'dcim/sites','cluster':'virtualization/clusters','platform':'dcim/platforms',
    'device_role':'dcim/device-roles','device_type':'dcim/device-types','cluster_type':'virtualization/cluster-types'}

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
        if action=='validate':
            selections=payload.get('selections')
            if not isinstance(selections,list) or not 6<=len(selections)<=21: raise ProbeError('RESPONSE_INVALID')
            result=[]
            for choice in selections:
                kind=choice.get('kind');identifier=choice.get('id')
                if kind not in ENDPOINTS or type(identifier) is not int or identifier<=0: raise ProbeError('RESPONSE_INVALID')
                fresh=project(kind,get(kind,str(identifier)+'/'))
                if fresh['fingerprint']!=choice.get('fingerprint'): raise ProbeError('CATALOG_CHANGED')
                result.append(dict(kind=kind,**fresh))
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
