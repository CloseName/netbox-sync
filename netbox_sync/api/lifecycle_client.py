"""Bounded, no-retry lifecycle worker client; no filesystem capability in Web."""
import json
import socket
from .operation_dto import LifecycleDTO


class LifecycleRequestError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class LifecycleClient:
    def __init__(self, path):
        self.path = path

    def operation_evidence(self):
        from ..local_control import request
        from datetime import datetime
        import time
        deadline=time.monotonic()+5
        plans, uncertain, after = {}, set(), ''
        for _ in range(200):
            remaining=deadline-time.monotonic()
            if remaining<=0: raise LifecycleRequestError('LIFECYCLE_UNAVAILABLE')
            value=request(self.path, {'action':'source_evidence','after':after},timeout=remaining)['result']
            for row in value['sources']:
                source=row['source_instance']
                if source<=after or source in plans: raise ValueError('Invalid evidence page')
                plans[source]={'status':row['plan_status'], 'apply_allowed':False if row['plan_blocked'] else None,
                    'finished_at':datetime.fromisoformat(row['plan_checked_at']) if row['plan_checked_at'] else None}
                if row['outcome_unconfirmed']: uncertain.add(source)
            if value['next'] is None: return plans, uncertain
            if value['next']<=after: raise ValueError('Invalid evidence cursor')
            after=value['next']
        raise LifecycleRequestError('LIFECYCLE_UNAVAILABLE')

    def retirement(self,action,source,**payload):
        from ..local_control import request,ControlError
        if action not in {'context','review','execute','resume','status'}:raise LifecycleRequestError('REQUEST_INVALID')
        try:
            value=request(self.path,{'action':'retirement_'+action,'source_instance':source,**payload},
                          timeout=60,response_limit=2*1024*1024)['result']
            if value.get('source_instance')!=source:raise ValueError()
            return value
        except ControlError as exc:raise LifecycleRequestError(exc.code) from None
        except Exception:raise LifecycleRequestError('RETIREMENT_UNAVAILABLE') from None

    def reconciliation(self,action,source,**payload):
        from ..local_control import request,ControlError
        if action not in {'review','confirm'}:raise LifecycleRequestError('REQUEST_INVALID')
        try:return request(self.path,{'action':'run_reconciliation_'+action,'source_instance':source,**payload},timeout=60,response_limit=2*1024*1024)['result']
        except ControlError as exc:raise LifecycleRequestError(exc.code) from None
        except Exception:raise LifecycleRequestError('LIFECYCLE_UNAVAILABLE') from None

    def identity(self,action,source,**payload):
        from ..local_control import request,ControlError
        if action not in {'describe','confirm'}:raise LifecycleRequestError('REQUEST_INVALID')
        try:
            return request(self.path,{'action':'identity_'+action,'source_instance':source,**payload},timeout=15)['result']
        except ControlError as exc:raise LifecycleRequestError(exc.code) from None
        except Exception:raise LifecycleRequestError('LIFECYCLE_UNAVAILABLE') from None

    def recovery(self, action, source, **payload):
        from ..local_control import request,ControlError
        if action not in {'inventory','records','retired_evidence','describe','prepare','credentials','complete','abandon','status'}:
            raise LifecycleRequestError('REQUEST_INVALID')
        try:
            return request(self.path,{'action':'recovery_'+action,'source_instance':source,**payload},timeout=100,response_limit=2*1024*1024)['result']
        except ControlError as exc:raise LifecycleRequestError(exc.code) from None
        except Exception:raise LifecycleRequestError('LIFECYCLE_UNAVAILABLE') from None

    def placement(self, source):
        from ..local_control import request, ControlError
        from .dto import DiscoveryHostDTO
        try:
            value = request(self.path, {'action':'read_placement','source_instance':source}, timeout=15)['result']
            if value['source_instance'] != source or not 1 <= len(value['preview']['hosts']) <= 16:
                raise ValueError()
            for host in value['preview']['hosts']:
                DiscoveryHostDTO.model_validate(host)
            return value
        except ControlError as exc:
            raise LifecycleRequestError(exc.code) from None
        except Exception:
            raise LifecycleRequestError('LIFECYCLE_UNAVAILABLE') from None

    def request(self, source, payload=None, action=None):
        request = {'action':action or ('source_lifecycle' if payload is None else 'remove_source'),
                   'source_instance':source, **(payload or {})}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(15)
                connection.connect(self.path)
                connection.sendall(json.dumps(request).encode()+b'\n')
                raw = b''
                while not raw.endswith(b'\n') and len(raw) < 8192:
                    part = connection.recv(8192-len(raw))
                    if not part:
                        break
                    raw += part
            response = json.loads(raw)
            if response.get('ok') is not True:
                raise LifecycleRequestError(response.get('error','LIFECYCLE_UNAVAILABLE'))
            result = LifecycleDTO.model_validate(response['result'])
            if result.source_instance != source:
                raise ValueError()
            return result
        except LifecycleRequestError:
            raise
        except Exception:
            raise LifecycleRequestError('LIFECYCLE_UNAVAILABLE') from None
