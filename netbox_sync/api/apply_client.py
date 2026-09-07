"""Credential-blind client for the dedicated manual apply worker."""

import json
import socket

from ..source_config import SOURCE_INSTANCE_PATTERN


class ApplyRequestError(RuntimeError):
    """Stable, secret-free apply transport failure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ApplyWorkerClient:
    """Expose only prepare/apply capabilities over a local Unix socket."""

    def __init__(self, socket_path, connector=socket.socket):
        self._socket_path = socket_path
        self._connector = connector

    def _request(self, payload):
        instance = payload.get('source_instance', '')
        if not SOURCE_INSTANCE_PATTERN.fullmatch(instance) or not self._socket_path:
            raise ApplyRequestError('APPLY_UNAVAILABLE')
        try:
            with self._connector(socket.AF_UNIX, socket.SOCK_STREAM) as connection:  # pylint: disable=no-member
                connection.settimeout(310)
                connection.connect(self._socket_path)
                connection.sendall(json.dumps(payload).encode())
                connection.shutdown(socket.SHUT_WR)
                chunks = []
                size = 0
                while True:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 65536:
                        raise ValueError('response too large')
                    chunks.append(chunk)
                response = json.loads(b''.join(chunks))
        except (OSError, ValueError, json.JSONDecodeError):
            raise ApplyRequestError('APPLY_UNAVAILABLE') from None
        if not isinstance(response, dict) or response.get('ok') is not True:
            code = response.get('error') if isinstance(response, dict) else None
            raise ApplyRequestError(code if isinstance(code, str) else 'APPLY_UNAVAILABLE')
        if not isinstance(response.get('result'), dict):
            raise ApplyRequestError('APPLY_RESPONSE_INVALID')
        return response['result']

    def prepare(self, source_instance, plan_digest, operation_id=None):
        """Request a capability for a server-recomputed exact digest."""
        return self._request({'operation': 'prepare', 'source_instance': source_instance,
                              'plan_digest': plan_digest, **({'operation_id': str(operation_id)} if operation_id else {})})

    def apply(self, source_instance, confirmation_token):
        """Consume one opaque capability; never accept operations from the browser."""
        return self._request({'operation': 'apply', 'source_instance': source_instance,
                              'confirmation_token': confirmation_token})
