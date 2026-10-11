"""Read-only, transport-independent source visibility with explicit public fields."""

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from ..source_config import SOURCE_INSTANCE_PATTERN
from .observability import ErrorCode


class SourceReadError(Exception):
    """Safe classified failure, never a driver exception or registry payload."""

    def __init__(self, code=ErrorCode.REGISTRY_UNAVAILABLE):
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True)
class SourceView:
    """Allowlisted operational metadata; no internal ID, settings or credentials."""

    source_instance: str
    type: str
    name: str
    address: str
    enabled: bool
    sync_enabled: bool
    verify_ssl: bool
    sync_interval_seconds: int
    site_slug: str
    cluster_name: str
    platform_slug: str
    device_role_slug: str
    device_type_slug: str
    cluster_type_slug: str
    legacy_identity_owner: bool
    status: str
    sync_calendar: dict | None = None
    schedule_changed_at: object | None = None


def source_view(row):
    """Fail closed on malformed metadata; never echo credential-bearing URLs."""
    fields = ('source_instance', 'name', 'address', 'site_slug', 'cluster_name',
              'platform_slug', 'device_role_slug', 'device_type_slug', 'cluster_type_slug')
    try:
        for name in fields:
            value = row[name]
            if (not isinstance(value, str) or not value.strip() or len(value) > 1024
                    or any(ord(char) < 32 for char in value)):
                raise ValueError('Invalid public text')
        if not SOURCE_INSTANCE_PATTERN.fullmatch(row['source_instance']):
            raise ValueError('Invalid instance')
        if row['source_type'] not in ('proxmox', 'esxi'):
            raise ValueError('Unsupported source')
        address = row['address']
        parsed = urlsplit(address if '://' in address else '//' + address)
        if (not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or '%' in address
                or ('://' in address and parsed.scheme not in ('http', 'https'))):
            raise ValueError('Unsafe endpoint')
        # Paths can contain opaque credentials: expose only host/port or an origin URL.
        if parsed.path not in ('', '/'):
            raise ValueError('Endpoint path is not public metadata')
        _ = parsed.port
        flags = ('enabled', 'sync_enabled', 'verify_ssl', 'legacy_identity_owner')
        if any(not isinstance(row[name], bool) for name in flags):
            raise ValueError('Invalid flag')
        interval = row['sync_interval_seconds']
        if not isinstance(interval, int) or isinstance(interval, bool) or interval <= 0:
            raise ValueError('Invalid interval')
        status = 'disabled' if not row['enabled'] else (
            'enabled' if row['sync_enabled'] else 'sync_disabled'
        )
        from ..calendar_schedule import validate_calendar
        calendar = validate_calendar(row.get('sync_calendar'))
        return SourceView(
            **{name: row[name] for name in fields},
            **{name: row[name] for name in flags},
            type=row['source_type'], sync_interval_seconds=interval, status=status,
            sync_calendar=calendar, schedule_changed_at=row.get('schedule_changed_at'),
        )
    except (KeyError, TypeError, ValueError):
        raise SourceReadError(ErrorCode.SOURCE_DATA_INVALID) from None


class SourceReadPort(Protocol):
    """Return only the projection needed by the public source model."""

    def read(self, source_instance=None):
        """Read all sources or one exact instance without mutations."""


class SourceVisibilityService:
    """Application policy, independent of FastAPI and Pydantic."""

    def __init__(self, reader: SourceReadPort):
        self._reader = reader

    def list_sources(self):
        """Return an immutable snapshot; malformed data fails the whole response."""
        return tuple(source_view(row) for row in self._reader.read())

    def get_source(self, source_instance):
        """Exact matching only; never use display names or fuzzy matching."""
        if not SOURCE_INSTANCE_PATTERN.fullmatch(source_instance):
            raise SourceReadError(ErrorCode.SOURCE_NOT_FOUND)
        rows = self._reader.read(source_instance)
        if not rows:
            raise SourceReadError(ErrorCode.SOURCE_NOT_FOUND)
        if len(rows) != 1:
            raise SourceReadError(ErrorCode.SOURCE_DATA_INVALID)
        view = source_view(rows[0])
        if view.source_instance != source_instance:
            raise SourceReadError(ErrorCode.SOURCE_DATA_INVALID)
        return view
