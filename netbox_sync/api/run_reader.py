"""Read-only PostgreSQL adapter for synchronization history."""

import psycopg

from ..run_history import RunRepository
from ..application.diagnostics import HistorySnapshot


class PostgresRunReader:
    """Expose only list/detail through a transaction-read-only connection."""

    def __init__(self, settings, connector=psycopg.connect):
        self._settings = settings
        self._connector = connector

    def _repository(self):
        if not self._settings.registry_dsn:
            raise RuntimeError('history unavailable')

        def connect():
            connection = self._connector(
                self._settings.registry_dsn, connect_timeout=3,
                options='-c statement_timeout=2000 -c default_transaction_read_only=on',
            )
            connection.read_only = True
            return connection
        return RunRepository(connect, self._settings.registry_schema)

    def list_runs(self, **filters):
        """Read bounded newest-first history."""
        return self._repository().list_runs(**filters)

    def plan_run(self, source, digest, finished_at):
        return self._repository().plan_run(source, digest, finished_at)

    def get_run(self, run_id):
        """Read one public UUID."""
        return self._repository().get_run(run_id)

    def diagnostics_snapshot(self, stale_before, stale_limit):
        """Use a fixed number of bounded/indexed history queries, never N+1 reads."""
        repository = self._repository()
        return HistorySnapshot(
            repository.latest_by_source(),
            repository.latest_by_source(status='SUCCEEDED'),
            repository.latest_by_source(trigger='scheduled'),
            repository.latest_by_source(trigger='manual'),
            repository.stale_running(stale_before, stale_limit),
            repository.latest_by_source(trigger='scheduled', status='SUCCEEDED'),
            repository.latest_by_source(trigger='scheduled', status='RUNNING'),
        )

    def scheduled_for_source(self, source_instance):
        """Return bounded newest scheduled history for one source."""
        return self._repository().list_runs(
            source_instance=source_instance, trigger='scheduled', limit=100)
