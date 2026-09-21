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

def validate(path,references,host_types,preview, *, pending_cluster=False):
    required={'site','platform','device_role','cluster_type'} | (set() if pending_cluster else {'cluster'})
    if set(references)!=required or not preview:
        raise CatalogError('SELECTION_REQUIRED')
    hosts={row['id'] for row in preview['hosts']}
    if set(host_types)!=hosts: raise CatalogError('HOST_MAPPING_REQUIRED')
    choices=[dict(kind=kind,**{k:row.get(k) for k in ('id','fingerprint')}) for kind,row in references.items()]
    choices += [dict(kind='device_type',**{k:row.get(k) for k in ('id','fingerprint')}) for row in host_types.values()]
    checked=call(path,{'action':'validate','selections':choices})['selections']
    refs={row['kind']:{k:v for k,v in row.items() if k!='kind'} for row in checked[:len(references)]}
    types={key:{k:v for k,v in row.items() if k!='kind'} for key,row in zip(host_types,checked[len(references):])}
    if pending_cluster:
        return dict(version=1,references=refs,host_types=types,hosts=preview['hosts'])
    cluster=refs['cluster'];site=refs['site'];ctype=refs['cluster_type']
    if (cluster.get('type') or {}).get('id')!=ctype['id'] or cluster.get('scope_type')!='dcim.site' or cluster.get('scope_id')!=site['id']:
        raise CatalogError('CLUSTER_SCOPE_MISMATCH')
    return dict(version=1,references=refs,host_types=types,hosts=preview['hosts'])


def create_call(path,payload):
    try: result=request(path,payload,timeout=33)['result']
    except ControlError as exc:
        # These lock refusals occur before a catalog child can send its POST.
        # Transport failures still have an unknown outcome.
        raise CatalogError('BUSY' if exc.code in {'BOOTSTRAP_BUSY','SOURCE_APPLY_ACTIVE'} else 'UNAVAILABLE') from None
    if 'status' not in result: raise CatalogError(result.get('error','UNAVAILABLE'))
    return result
