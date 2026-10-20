"""Source-type executor dispatch without adapter-specific logic."""

from types import MappingProxyType

from .source_config import SourceConfig


class UnsupportedSourceTypeError(RuntimeError):
    """No executor is registered for a source type."""


class SourceExecutorDispatch:
    """Immutable source-type to executor dispatch table."""

    def __init__(self, executors):
        configured = dict(executors)
        if not configured:
            raise ValueError("at least one source executor must be configured")
        for source_type, executor in configured.items():
            if not isinstance(source_type, str) or not source_type:
                raise ValueError("executor source types must be non-empty strings")
            if not callable(executor):
                raise TypeError("source executors must be callable")
        self._executors = MappingProxyType(configured)

    def execute(self, source):
        """Dispatch one immutable SourceConfig or fail closed for its type."""

        if not isinstance(source, SourceConfig):
            raise TypeError("source must be a SourceConfig")
        executor = self._executors.get(source.source_type)
        if executor is None:
            raise UnsupportedSourceTypeError(f"unsupported source type {source.source_type!r}")
        return executor(source)
