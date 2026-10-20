"""Single-source configuration selection and guarded registry bootstrap."""

import json
import os
from dataclasses import dataclass, fields, replace
from pathlib import Path

import psycopg

from .source_config import SecretReference, SourceConfig, SourceCredentials
from .application.scheduling import SchedulerSourceInput
from .source_registry import SourceRegistry


LEGACY_MODE = "legacy"
REGISTRY_MODE = "registry"
REGISTRY_ALL_MODE = "registry-all"
RUNTIME_MODES = frozenset({LEGACY_MODE, REGISTRY_MODE, REGISTRY_ALL_MODE})


class SourceBootstrapError(RuntimeError):
    """Runtime source selection or bootstrap failed closed."""


@dataclass(frozen=True)
class BootstrapChange:
    """One deterministic, display-safe configuration difference."""

    field: str
    before: str
    after: str


@dataclass(frozen=True)
class BootstrapResult:
    """Outcome of a dry-run or explicitly confirmed bootstrap."""

    action: str
    source_id: str
    confirmed: bool
    changes: tuple[BootstrapChange, ...]

    @property
    def created(self):
        """Return the number of sources planned for creation."""

        return int(self.action == "create")

    @property
    def updated(self):
        """Return the number of sources planned for update."""

        return int(self.action == "update")

    @property
    def noop(self):
        """Return the number of already matching sources."""

        return int(self.action == "noop")


def _required(environ, variable_name):
    value = environ.get(variable_name, "").strip()
    if not value:
        raise SourceBootstrapError(f"{variable_name} must be configured")
    return value


def runtime_source_mode(environ):
    """Return explicit mode, preserving legacy as the absent-variable default."""

    if "SOURCE_CONFIG_MODE" not in environ:
        return LEGACY_MODE
    mode = environ.get("SOURCE_CONFIG_MODE", "").strip().lower()
    if mode not in RUNTIME_MODES:
        raise SourceBootstrapError("SOURCE_CONFIG_MODE must be legacy, registry, or registry-all")
    return mode


def _postgres_registry(dsn, schema):
    def connect():
        return psycopg.connect(dsn)

    return SourceRegistry(connect, schema)


def load_runtime_source_config(environ=None, registry_factory=None):
    """Load exactly one SourceConfig without registry-to-legacy fallback."""

    if environ is None:
        environ = os.environ
    mode = runtime_source_mode(environ)
    if mode == LEGACY_MODE:
        return SourceConfig.from_legacy_environment(environ)
    if mode == REGISTRY_ALL_MODE:
        raise SourceBootstrapError("registry-all mode requires multi-source configuration loading")

    dsn = _required(environ, "NETBOX_SYNC_REGISTRY_DSN")
    schema = _required(environ, "NETBOX_SYNC_REGISTRY_SCHEMA")
    source_id = _required(environ, "SOURCE_ID")
    factory = registry_factory or _postgres_registry
    registry = factory(dsn, schema)
    config = registry.get_source_config(source_id)
    if config is None:
        raise SourceBootstrapError(f"Registry source id {source_id!r} was not found")
    if not config.enabled:
        raise SourceBootstrapError(f"Registry source id {source_id!r} is disabled")
    if not config.sync_enabled:
        raise SourceBootstrapError(f"Registry source id {source_id!r} has sync disabled")
    return config


def load_runtime_source_configs(environ=None, registry_factory=None):
    """Load all runnable configs for explicit multi-source registry mode."""

    if environ is None:
        environ = os.environ
    if runtime_source_mode(environ) != REGISTRY_ALL_MODE:
        raise SourceBootstrapError("multi-source loading requires SOURCE_CONFIG_MODE=registry-all")
    dsn = _required(environ, "NETBOX_SYNC_REGISTRY_DSN")
    schema = _required(environ, "NETBOX_SYNC_REGISTRY_SCHEMA")
    factory = registry_factory or _postgres_registry
    registry = factory(dsn, schema)
    configs = registry.list_runnable_sources()
    if not configs:
        raise SourceBootstrapError("Registry has no runnable sources")
    legacy_owners = [config.id for config in configs if config.legacy_identity_owner]
    if len(legacy_owners) > 1:
        raise SourceBootstrapError("Registry has multiple runnable legacy identity owners")
    return configs


def load_scheduler_source_configs(environ=None, registry_factory=None):
    """Load all registry sources so a fixed tick can classify each one."""
    if environ is None:
        environ = os.environ
    if runtime_source_mode(environ) != REGISTRY_ALL_MODE:
        raise SourceBootstrapError("scheduler requires SOURCE_CONFIG_MODE=registry-all")
    registry = (registry_factory or _postgres_registry)(
        _required(environ, "NETBOX_SYNC_REGISTRY_DSN"), _required(environ, "NETBOX_SYNC_REGISTRY_SCHEMA")
    )
    load_results = registry.list_sources_isolated()
    configs = tuple(
        SchedulerSourceInput(result.record.to_source_config() if result.valid else None) for result in load_results
    )
    owners = [
        item.config.id
        for item in configs
        if item.config is not None
        and item.config.enabled
        and item.config.sync_enabled
        and item.config.legacy_identity_owner
    ]
    if len(owners) > 1:
        raise SourceBootstrapError("Registry has multiple runnable legacy identity owners")
    return configs


def _registry_credential_reference(reference):
    provider = "env" if reference.provider == "environment" else reference.provider
    key = Path(reference.key).name if provider == "file" else reference.key
    return SecretReference(provider=provider, key=key)


def registry_compatible_config(config):
    """Convert legacy provider spelling without resolving secret values."""

    credentials = SourceCredentials(
        username=config.credentials.username,
        token_id=_registry_credential_reference(config.credentials.token_id),
        token_secret=_registry_credential_reference(config.credentials.token_secret),
    )
    return replace(config, credentials=credentials)


def _redact_settings(value):
    if isinstance(value, dict) or hasattr(value, "items"):
        result = {}
        for key, item in value.items():
            lowered = str(key).casefold()
            if any(part in lowered for part in ("password", "secret", "token")):
                result[str(key)] = "<redacted>"
            else:
                result[str(key)] = _redact_settings(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact_settings(item) for item in value]
    return value


def _safe_value(value, field_name=None):
    if isinstance(value, SecretReference):
        return f"{value.provider}:{value.key}"
    if isinstance(value, SourceCredentials):
        return json.dumps(
            {
                "username": value.username,
                "token_id": _safe_value(value.token_id),
                "token_secret": _safe_value(value.token_secret),
            },
            sort_keys=True,
        )
    if hasattr(value, "__dataclass_fields__"):
        return json.dumps(
            {item.name: getattr(value, item.name) for item in fields(value)},
            sort_keys=True,
        )
    if isinstance(value, dict) or hasattr(value, "items"):
        safe_mapping = dict(value)
        if field_name == "settings":
            safe_mapping = _redact_settings(safe_mapping)
        return json.dumps(safe_mapping, sort_keys=True)
    return repr(value)


def _changes(existing, candidate):
    mutable_fields = (
        "name",
        "address",
        "enabled",
        "sync_enabled",
        "sync_interval_seconds",
        "verify_ssl",
        "target",
        "credentials",
        "legacy_identity_owner",
        "settings",
    )
    return tuple(
        BootstrapChange(
            field=field_name,
            before=_safe_value(getattr(existing, field_name), field_name),
            after=_safe_value(getattr(candidate, field_name), field_name),
        )
        for field_name in mutable_fields
        if getattr(existing, field_name) != getattr(candidate, field_name)
    )


def _assert_matching_identity(existing, candidate):
    for field_name in ("id", "source_instance", "source_type"):
        if getattr(existing, field_name) != getattr(candidate, field_name):
            raise SourceBootstrapError(f"bootstrap conflict: immutable {field_name} differs")


def bootstrap_legacy_source(registry, legacy_config, confirmed=False):
    """Plan or apply one legacy source registration; dry-run is the default."""

    if not isinstance(confirmed, bool):
        raise TypeError("confirmed must be a boolean")
    candidate = registry_compatible_config(legacy_config)
    by_id = registry.get_source(candidate.id)
    by_instance = registry.get_by_source_instance(candidate.source_instance)
    if by_id is not None:
        _assert_matching_identity(by_id.config, candidate)
    if by_instance is not None:
        _assert_matching_identity(by_instance.config, candidate)
    if by_id is not None and by_instance is not None and by_id.id != by_instance.id:
        raise SourceBootstrapError("bootstrap conflict: id and source_instance select different sources")

    existing = by_id or by_instance
    if existing is None:
        if confirmed:
            registry.create_source(candidate)
        return BootstrapResult(
            action="create",
            source_id=candidate.id,
            confirmed=confirmed,
            changes=(),
        )

    changes = _changes(existing.config, candidate)
    if not changes:
        return BootstrapResult(
            action="noop",
            source_id=candidate.id,
            confirmed=confirmed,
            changes=(),
        )
    if confirmed:
        registry.update_source(
            candidate.id,
            **{change.field: getattr(candidate, change.field) for change in changes},
        )
    return BootstrapResult(
        action="update",
        source_id=candidate.id,
        confirmed=confirmed,
        changes=changes,
    )
