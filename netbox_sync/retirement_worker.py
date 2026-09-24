"""NetBox-only Unix worker; no DB, provider secrets or host control access."""
import json
import logging
import os
import subprocess
import sys
from uuid import UUID
from .local_control import serve, ControlError, request
from .retirement_codes import REASONS
DIAGNOSTIC_CODES=frozenset({'GUARD_CONNECTION_FAILED','GUARD_TLS_FAILED','GUARD_TIMEOUT',
    'GUARD_CAPABILITY_MISMATCH','GUARD_RESPONSE_INVALID','GUARD_RESPONSE_UNCONFIRMED',
    'PERMISSION_DENIED','GUARD_INSTANCE_CHANGED','REQUEST_CONFLICT','REQUEST_REFUSED',
    'AUTHENTICATION_REQUIRED','TOKEN_WRITE_REQUIRED','GUARD_AUDIT_PERMISSION_REQUIRED','GUARD_SOURCE_SCOPE_DENIED','GUARD_OBJECT_VIEW_DENIED','CREATION_OWNERSHIP_UNPROVEN','OWNERSHIP_CONFLICT',
    'PLACEMENT_CHANGED','DEPENDENCIES_CHANGED','OBJECT_GENERATION_CHANGED','EXTERNAL_FIELD_UPDATE',
    'PROTECTED_DEPENDENCY','REQUEST_NOT_FOUND','RETIREMENT_REFUSED'})
MAX_RESPONSE=2*1024*1024
CHILD_TIMEOUT=45


def child(payload):
    import requests
    from urllib.parse import urlsplit
    from .retirement_transport import GuardClient
    from .netbox_tls import configure_session
    from .netbox_auth import authorization
    from .api.egress import EgressPolicy,pinned_dns
    parts=urlsplit(payload['url']);port=parts.port or 443
    host,address=EgressPolicy(allowed_hosts=(parts.hostname,)).resolve(parts.hostname,port)
    with pinned_dns(host,address,port),requests.Session() as session:
        configure_session(session)
        client=GuardClient(session,payload['url'],authorization(payload['token']),payload['instance'])
        capabilities=client.capabilities()
        if capabilities.get('source_tree_retirement') is not True:
            raise ControlError('RETIREMENT_UNAVAILABLE')
        value=payload['request']
        if value['action']=='audit':
            from .retirement_transport import GuardTransportError
            if capabilities.get('source_audit') is not True:raise GuardTransportError('GUARD_CAPABILITY_MISMATCH')
            if capabilities.get('audit_permission') is not True:raise GuardTransportError('GUARD_AUDIT_PERMISSION_REQUIRED')
            if capabilities.get('token_write_enabled') is not True:raise GuardTransportError('TOKEN_WRITE_REQUIRED')
            result=client.audit_source(value['source_instance'],value['operation_id'])
        elif value['action']=='review':
            result=client.review_source(value['operation_id'],value['source_instance'],value['cluster_id'])
        elif value['action']=='execute':
            result=client.execute_source(value['operation_id'],value['digest'])
        else:
            result=client.receipt(value['operation_id'])
        return {'guard_instance':payload['instance'],'result':result}


def handle(value):
    from .source_config import SOURCE_INSTANCE_PATTERN
    from .bootstrap_state import runtime_netbox
    import re
    action=value.get('action');fields={'action','operation_id'}
    if action=='audit':fields|={'source_instance'}
    elif action=='review': fields|={'source_instance','cluster_id'}
    elif action=='execute': fields|={'digest'}
    elif action!='receipt': raise ControlError('CONTROL_REQUEST_INVALID')
    if set(value)!=fields: raise ControlError('CONTROL_REQUEST_INVALID')
    try:
        UUID(value['operation_id'])
        instance=str(UUID(os.environ.get('NETBOX_SYNC_GUARD_INSTANCE','')))
    except (ValueError,TypeError): raise ControlError('RETIREMENT_UNAVAILABLE') from None
    if action=='audit' and (not isinstance(value['source_instance'],str) or not SOURCE_INSTANCE_PATTERN.fullmatch(value['source_instance'])):
        raise ControlError('CONTROL_REQUEST_INVALID')
    if action=='review' and (not isinstance(value['source_instance'],str)
                            or not SOURCE_INSTANCE_PATTERN.fullmatch(value['source_instance'])
                            or type(value['cluster_id']) is not int or value['cluster_id']<=0):
        raise ControlError('CONTROL_REQUEST_INVALID')
    if action=='execute' and (not isinstance(value['digest'],str) or not re.fullmatch('[a-f0-9]{64}',value['digest'])):
        raise ControlError('CONTROL_REQUEST_INVALID')
    url,token=runtime_netbox(os.environ.get('NETBOX_SYNC_NETBOX_CONFIG_FILE','/run/secrets/netbox/bootstrap.json'),'apply')
    payload={'url':url,'token':token,'instance':instance,'request':value}
    try:
        from .child_process import child_process, stop_child
        # Do not inherit application/DB/proxy credentials into the HTTP child.
        environment={key:value for key,value in os.environ.items()
                     if key in ('PATH','SYSTEMROOT','WINDIR','TEMP','TMP','LANG','LC_ALL')}
        environment['PYTHONDONTWRITEBYTECODE']='1'
        with child_process(subprocess.Popen,
                [sys.executable,'-B','-m','netbox_sync.retirement_worker','--child'],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                env=environment) as process:
            try:
                output,_=process.communicate(json.dumps(payload).encode(),timeout=CHILD_TIMEOUT)
            except subprocess.TimeoutExpired:
                stop_child(process)
                raise ControlError('RETIREMENT_UNCERTAIN' if action=='execute' else 'RETIREMENT_UNAVAILABLE') from None
            if process.returncode or len(output)>MAX_RESPONSE:raise ValueError()
        result=json.loads(output)
        if result.get('error'):
            code=result['error'] if result['error'] in DIAGNOSTIC_CODES else 'RETIREMENT_REFUSED'
            logging.getLogger(__name__).warning('retirement_operation=%s action=%s code=%s',
                                               str(UUID(value['operation_id'])),action,code)
            raise ControlError('RETIREMENT_UNCERTAIN' if result.get('uncertain') else REASONS.get(code,'RETIREMENT_BLOCKED'))
        if set(result)!={'guard_instance','result'}:raise ValueError()
        return result
    except ControlError: raise
    except Exception: raise ControlError('RETIREMENT_UNCERTAIN' if action=='execute' else 'RETIREMENT_UNAVAILABLE') from None


class RetirementClient:
    def __init__(self,path):self.path=path
    def call(self,action,operation,**fields):
        return request(self.path,{'action':action,'operation_id':str(operation),**fields},
                       timeout=50,response_limit=MAX_RESPONSE)['result']


def main():
    if sys.argv[1:]==['--child']:
        try: result=child(json.loads(sys.stdin.buffer.read(32769)))
        except Exception as exc:
            result={'error':getattr(exc,'code',None) if getattr(exc,'code',None) in DIAGNOSTIC_CODES else 'RETIREMENT_REFUSED',
                    'uncertain':getattr(exc,'uncertain',True)}
        sys.stdout.write(json.dumps(result));return
    # Only lifecycle mounts this socket. API has neither this mount nor token.
    serve(os.environ.get('NETBOX_SYNC_RETIREMENT_SOCKET','/run/netbox-sync-retirement/worker.sock'),handle,allowed_uid=0)


if __name__=='__main__':main()
