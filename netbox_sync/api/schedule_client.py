"""Safe API client for the schedule-control Unix socket."""
# AF_UNIX is intentionally a deployment-platform API.
# pylint: disable=no-member

import json
import socket


class ScheduleRequestError(RuntimeError):
    """Closed control-plane failure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ScheduleWorkerClient:
    """Send only typed schedule updates with a bounded response."""

    def __init__(self, socket_path, connector=socket.socket):
        self._socket, self._connector = socket_path, connector

    def update(self, source_instance, values):
        payload = {'operation': 'update_schedule', 'source_instance': source_instance, **values}
        try:
            with self._connector(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(3)
                connection.connect(self._socket)
                connection.sendall(json.dumps(payload).encode())
                connection.shutdown(socket.SHUT_WR)
                raw = connection.recv(4097)
            if len(raw) > 4096:
                raise ValueError
            response = json.loads(raw)
        except (OSError, ValueError, json.JSONDecodeError):
            raise ScheduleRequestError('CONTROL_WORKER_UNAVAILABLE') from None
        if not isinstance(response, dict) or response.get('ok') is not True:
            code = response.get('error') if isinstance(response, dict) else None
            allowed = {'SCHEDULE_INVALID', 'SCHEDULE_CONFLICT', 'SOURCE_NOT_FOUND',
                       'CONTROL_REQUEST_FAILED'}
            raise ScheduleRequestError(code if code in allowed else 'CONTROL_REQUEST_FAILED')
        result = response.get('result')
        if (not isinstance(result, dict)
                or set(result) not in ({'source_instance', 'sync_enabled', 'sync_interval_seconds'},
                    {'source_instance', 'sync_enabled', 'sync_interval_seconds', 'sync_calendar', 'schedule_changed_at'})
                or result.get('source_instance') != source_instance
                or not isinstance(result.get('sync_enabled'), bool)
                or not isinstance(result.get('sync_interval_seconds'), int)
                or isinstance(result.get('sync_interval_seconds'), bool)):
            raise ScheduleRequestError('CONTROL_REQUEST_FAILED')
        return result
