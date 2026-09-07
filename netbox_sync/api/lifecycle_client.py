"""Bounded, no-retry lifecycle broker client; no filesystem capability in Web."""
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

    def request(self, source, payload=None):
        request = {'action':'source_lifecycle' if payload is None else 'remove_source',
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
