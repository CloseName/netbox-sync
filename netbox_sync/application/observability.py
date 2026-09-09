"""Allowlisted structured events, without arbitrary exception or payload fields."""

from datetime import datetime, timezone
from enum import Enum

from .contracts import RunContext


class ErrorCode(str, Enum):
    """Stable public codes; adapters must classify without exposing exceptions."""

    SOURCE_AUTH_FAILED = 'SOURCE_AUTH_FAILED'
    SOURCE_UNREACHABLE = 'SOURCE_UNREACHABLE'
    SOURCE_TLS_FAILED = 'SOURCE_TLS_FAILED'
    SOURCE_CONFIG_INVALID = 'SOURCE_CONFIG_INVALID'
    SOURCE_SECRET_MISSING = 'SOURCE_SECRET_MISSING'
    NETBOX_AUTH_FAILED = 'NETBOX_AUTH_FAILED'
    NETBOX_UNREACHABLE = 'NETBOX_UNREACHABLE'
    NETBOX_TARGET_INVALID = 'NETBOX_TARGET_INVALID'
    REGISTRY_UNAVAILABLE = 'REGISTRY_UNAVAILABLE'
    SOURCE_NOT_FOUND = 'SOURCE_NOT_FOUND'
    SOURCE_DATA_INVALID = 'SOURCE_DATA_INVALID'
    SOURCE_UNSUPPORTED = 'SOURCE_UNSUPPORTED'
    SOURCE_CONNECTION_FAILED = 'SOURCE_CONNECTION_FAILED'
    SOURCE_DNS_FAILED = 'SOURCE_DNS_FAILED'
    SOURCE_TIMEOUT = 'SOURCE_TIMEOUT'
    SOURCE_DESTINATION_DENIED = 'SOURCE_DESTINATION_DENIED'
    SOURCE_ALREADY_EXISTS = 'SOURCE_ALREADY_EXISTS'
    SECRET_STORE_FAILED = 'SECRET_STORE_FAILED'
    REGISTRATION_FAILED = 'REGISTRATION_FAILED'
    REGISTRATION_UNCERTAIN = 'REGISTRATION_UNCERTAIN'
    REGISTRATION_UNAVAILABLE = 'REGISTRATION_UNAVAILABLE'
    ONBOARDING_TOKEN_INVALID = 'ONBOARDING_TOKEN_INVALID'
    RUN_PRECHECK_FAILED = 'RUN_PRECHECK_FAILED'
    RUN_APPLY_FAILED = 'RUN_APPLY_FAILED'
    RUN_INTERNAL_FAILED = 'RUN_INTERNAL_FAILED'


class Component(str, Enum):
    """Bounded component names, not user-supplied log labels."""

    API = 'api'
    APPLICATION = 'application'
    WORKER = 'worker'
    SCHEDULER = 'scheduler'


class RunEvent(str, Enum):
    """Fixed messages so secrets cannot enter free-form event text."""

    STARTED = 'Run started'
    PREFLIGHT_PASSED = 'Run preflight passed'
    SUCCEEDED = 'Run succeeded'
    FAILED = 'Run failed'


def run_event_record(context, component, event, *, error_code=None):
    """Build a JSON-ready event; do not configure logging or print anything."""

    if not isinstance(context, RunContext):
        raise TypeError('context must be RunContext')
    if not isinstance(component, Component) or not isinstance(event, RunEvent):
        raise TypeError('component and event must be catalog values')
    if error_code is not None and not isinstance(error_code, ErrorCode):
        raise TypeError('error_code must be a catalog value')
    if (event == RunEvent.FAILED) != (error_code is not None):
        raise ValueError('only failed events require an error_code')
    return {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'level': 'ERROR' if error_code else 'INFO',
        'component': component.value,
        'source_instance': context.source_instance,
        'run_id': str(context.run_id),
        'error_code': error_code.value if error_code else None,
        'message': event.value,
    }
