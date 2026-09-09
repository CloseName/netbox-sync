"""Authenticated API gateway: never sees the NetBox read token."""
from ..local_control import request,ControlError

class CatalogError(Exception):
    def __init__(self,code): self.code=code

def call(path,payload):
    if not path: raise CatalogError('UNAVAILABLE')
    try: result=request(path,{'action':'catalog','query':payload},timeout=33)['result']
    except ControlError: raise CatalogError('UNAVAILABLE') from None
    if 'error' in result: raise CatalogError(result['error'])
    return result

def validate(path,references,host_types,preview):
    if set(references)!={'site','cluster','platform','device_role','cluster_type'} or not preview:
        raise CatalogError('SELECTION_REQUIRED')
    hosts={row['id'] for row in preview['hosts']}
    if set(host_types)!=hosts: raise CatalogError('HOST_MAPPING_REQUIRED')
    choices=[dict(kind=kind,**{k:row.get(k) for k in ('id','fingerprint')}) for kind,row in references.items()]
    choices += [dict(kind='device_type',**{k:row.get(k) for k in ('id','fingerprint')}) for row in host_types.values()]
    checked=call(path,{'action':'validate','selections':choices})['selections']
    refs={row['kind']:{k:v for k,v in row.items() if k!='kind'} for row in checked[:5]}
    types={key:{k:v for k,v in row.items() if k!='kind'} for key,row in zip(host_types,checked[5:])}
    cluster=refs['cluster'];site=refs['site'];ctype=refs['cluster_type']
    if (cluster.get('type') or {}).get('id')!=ctype['id'] or cluster.get('scope_type')!='dcim.site' or cluster.get('scope_id')!=site['id']:
        raise CatalogError('CLUSTER_SCOPE_MISMATCH')
    return dict(version=1,references=refs,host_types=types,hosts=preview['hosts'])
