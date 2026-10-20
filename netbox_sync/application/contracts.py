"""Transport-independent contracts for future API and worker adapters."""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID, uuid4

from ..source_config import SecretReference, SOURCE_INSTANCE_PATTERN


@dataclass(frozen=True)
class RunContext:
    """One source execution ID, allocated once and propagated across layers."""

    source_instance: str
    run_id: UUID = field(default_factory=uuid4)

    def __post_init__(self):
        if not isinstance(self.run_id, UUID) or self.run_id.int == 0:
            raise ValueError("run_id must be a non-nil UUID")
        if not isinstance(self.source_instance, str) or not SOURCE_INSTANCE_PATTERN.fullmatch(self.source_instance):
            raise ValueError("source_instance must be a valid source identifier")


class SecretReader(Protocol):
    """Read-only port already satisfied by FileSecretResolver; no web exposure."""

    def resolve(self, reference: SecretReference) -> str:
        """Resolve only at the execution boundary; never serialize the result."""


class PreflightSubmitter(Protocol):
    """Future API/scheduler port; intentionally grants no apply permission."""

    def submit_preflight(self, context: RunContext) -> None:
        """Enqueue the supplied run ID once; durable implementation is deferred."""
