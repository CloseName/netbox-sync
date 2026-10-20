"""Bounded credential-blind Unix-socket worker health probe."""

import json
import socket


class WorkerHealthClient:
    """Check only the fixed health operation with a short timeout."""

    def __init__(self, socket_path, connector=socket.socket, timeout=1.0):
        self._socket_path = socket_path
        self._connector = connector
        self._timeout = timeout

    def health(self):
        """Return true only for the exact bounded worker response."""
        if not self._socket_path:
            return False
        try:
            family = getattr(socket, "AF_UNIX", 1)
            with self._connector(family, socket.SOCK_STREAM) as connection:
                connection.settimeout(self._timeout)
                connection.connect(self._socket_path)
                connection.sendall(b'{"operation":"health"}')
                connection.shutdown(socket.SHUT_WR)
                response = connection.recv(1025)
            if len(response) > 1024:
                return False
            value = json.loads(response)
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        return value == {"ok": True, "result": {"status": "ok"}}
