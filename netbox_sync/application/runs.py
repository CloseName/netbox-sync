"""Transport-neutral read service for synchronization history."""

from enum import Enum
from uuid import UUID

from ..run_history import RunStatus, RunTrigger
from ..source_config import SOURCE_INSTANCE_PATTERN


class RunReadErrorCode(str, Enum):
    """Stable public history read failures."""

    NOT_FOUND = 'RUN_NOT_FOUND'
    INVALID_FILTER = 'RUN_FILTER_INVALID'
    UNAVAILABLE = 'RUN_HISTORY_UNAVAILABLE'


class RunReadError(RuntimeError):
    """Safe history read failure."""

    def __init__(self, code):
        self.code = RunReadErrorCode(code)
        super().__init__(self.code.value)


class RunHistoryService:
    """Expose bounded reads without persistence credentials or SQL concerns."""

    def __init__(self, reader):
        self._reader = reader

    def list_runs(self, **filters):
        """Validate every public filter before reaching the SQL reader."""
        try:
            source_instance = filters.get('source_instance')
            if source_instance is not None and not SOURCE_INSTANCE_PATTERN.fullmatch(
                    source_instance):
                raise ValueError('invalid source_instance')
            source_type = filters.get('source_type')
            if source_type is not None and source_type not in ('proxmox', 'esxi'):
                raise ValueError('invalid source_type')
            if filters.get('trigger') is not None:
                RunTrigger(filters['trigger'])
            if filters.get('status') is not None:
                RunStatus(filters['status'])
            limit = filters.get('limit', 50)
            if not isinstance(limit, int) or not 1 <= limit <= 200:
                raise ValueError('invalid limit')
            if filters.get('cursor') is not None:
                UUID(str(filters['cursor']))
            return self._reader.list_runs(**filters)
        except ValueError as exc:
            raise RunReadError(RunReadErrorCode.INVALID_FILTER) from exc
        except Exception as exc:
            raise RunReadError(RunReadErrorCode.UNAVAILABLE) from exc

    def plan_run(self, source, digest, finished_at):
        try:
            return self._reader.plan_run(source, digest, finished_at)
        except Exception as exc:
            raise RunReadError(RunReadErrorCode.UNAVAILABLE) from exc

    def get_run(self, run_id):
        """Return one record or a stable not-found failure."""
        try:
            result = self._reader.get_run(run_id)
        except Exception as exc:
            raise RunReadError(RunReadErrorCode.UNAVAILABLE) from exc
        if result is None:
            raise RunReadError(RunReadErrorCode.NOT_FOUND)
        return result
