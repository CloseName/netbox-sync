"""Lifecycle-aware adapters without rewriting the established registry implementation."""
from psycopg import sql
from .source_reader import PostgresSourceReader
from .onboarding_adapters import RegistrationRegistry
from ..application.onboarding import OnboardingError
from ..application.observability import ErrorCode
from ..application.sources import SourceReadError
from ..schedule_worker import ScheduleStore, ScheduleWorkerError
from ..source_operations import source_gate


class ReservedSourceError(OnboardingError):
    """Use a distinct closed error without widening the general event catalog."""
    def __init__(self):
        super().__init__(ErrorCode.SOURCE_ALREADY_EXISTS)
        self.reserved_source_id = True


class ActiveSourceReader(PostgresSourceReader):
    """Keep the safe column projection and exclude durable identity reservations."""
    def read(self, source_instance=None):
        rows = super().read(source_instance)
        try:
            with self._connector(self._settings.registry_dsn, connect_timeout=3,
                                 options='-c statement_timeout=2000 -c default_transaction_read_only=on') as connection:
                removed = {row[0] for row in connection.execute(sql.SQL(
                    'SELECT source_instance FROM {}').format(sql.Identifier(
                        self._settings.registry_schema, 'source_tombstones'))).fetchall()}
            return tuple(row for row in rows if row['source_instance'] not in removed)
        except Exception:
            raise SourceReadError() from None


class LifecycleRegistrationRegistry(RegistrationRegistry):
    def find(self, instance):
        try:
            registry = self._registry()
            with registry._connect() as connection:
                removed = connection.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s')
                    .format(sql.Identifier(self._schema, 'source_tombstones')), (instance,)).fetchone()
            if removed:
                raise ReservedSourceError()
            return super().find(instance)
        except OnboardingError:
            raise
        except Exception:
            raise OnboardingError(ErrorCode.REGISTRATION_UNAVAILABLE) from None


class LifecycleScheduleStore(ScheduleStore):
    """Serialize the check/update against removal without broad UPDATE privileges."""
    def update(self, request):
        source = request['source_instance']
        try:
            with self._connector(self._dsn, connect_timeout=3,
                    options='-c statement_timeout=5000 -c lock_timeout=3000') as connection:
                with source_gate(connection, self._schema, source):
                    removed = connection.execute(sql.SQL('SELECT 1 FROM {} WHERE source_instance=%s')
                        .format(sql.Identifier(self._schema, 'source_tombstones')), (source,)).fetchone()
                    if removed:
                        raise ScheduleWorkerError('SOURCE_NOT_FOUND')
                    return super().update(request)
        except ScheduleWorkerError:
            raise
        except Exception:
            raise ScheduleWorkerError('CONTROL_REQUEST_FAILED') from None
