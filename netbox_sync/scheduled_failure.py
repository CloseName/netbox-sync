"""Bounded scheduler diagnostics: never serialize exceptions, URLs or payloads."""
from contextvars import ContextVar
from dataclasses import dataclass
import json
import re
import sys
from urllib.parse import urlsplit
from uuid import UUID

from .worker_failure import diagnostic

_STAGES = frozenset(('dispatch', 'credentials', 'provider', 'netbox', 'legacy_read', 'planning', 'apply'))
_ENDPOINTS = frozenset(('dcim.devices', 'dcim.interfaces', 'dcim.mac_addresses',
    'dcim.sites', 'dcim.device_roles', 'dcim.device_types', 'dcim.platforms',
    'virtualization.clusters', 'virtualization.cluster_types', 'virtualization.virtual_machines',
    'virtualization.interfaces', 'virtualization.virtual_disks',
    'ipam.ip_addresses', 'ipam.prefixes', 'ipam.vlans', 'extras.tags', 'extras.custom_fields'))
_current = ContextVar('scheduled_execution', default=None)

class ScheduledPlanBlocked(RuntimeError):
    code = 'PLAN_BLOCKED'


@dataclass
class ExecutionEvidence:
    stage: str = 'dispatch'
    plan: object = None
    writes_possible: bool = False
    run_id: object = None


def begin(run_id=None):
    evidence = ExecutionEvidence(run_id=run_id)
    return evidence, _current.set(evidence)


def end(token):
    _current.reset(token)


def mark(stage, plan=None):
    if stage not in _STAGES:
        raise ValueError('Unknown scheduled stage')
    evidence = _current.get()
    if evidence is not None:
        evidence.stage = stage
        if plan is not None:
            evidence.plan = plan
        if stage == 'apply':
            evidence.writes_possible = True


def _http(exc):
    # RequestError.req is a Response. Never read text/json/reason/headers/body.
    response = getattr(exc, 'req', None)
    if response is None:
        response = getattr(exc, 'response', None)
    status = getattr(response, 'status_code', getattr(exc, 'status_code', None))
    if type(status) is not int or not 100 <= status <= 599:
        return None
    value = {'status': status}
    request = getattr(response, 'request', None)
    method = getattr(request, 'method', None)
    if method in ('GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'HEAD', 'OPTIONS'):
        value['method'] = method
    url = getattr(request, 'url', None)
    if isinstance(url, str):
        try:
            parts = urlsplit(url).path.strip('/').split('/')
            endpoint = parts[1]+'.'+parts[2].replace('-', '_') if len(parts)>=3 and parts[0]=='api' else None
            if endpoint in _ENDPOINTS and (len(parts)==3 or len(parts)==4 and parts[3].isdigit()):
                value['endpoint'] = endpoint
        except ValueError:
            pass
    return value


def record(exc, evidence, run_id):
    try:
        identifier = str(UUID(str(run_id)))
    except (ValueError, TypeError, AttributeError):
        identifier = None
    name = type(exc).__name__
    value = dict(event='SCHEDULED_FAILURE', run_id=identifier, stage=evidence.stage,
        exception_class=name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]{0,100}', name) else 'Exception',
        frames=diagnostic(exc, 'planning')['frames'],
        write_outcome='MAY_HAVE_WRITTEN' if evidence.writes_possible else 'NOT_STARTED')
    current = exc
    seen = set()
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        details = _http(current)
        if details is not None:
            value['http'] = details
            break
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return value


def emit(exc, evidence, run_id):
    print(json.dumps(record(exc, evidence, run_id), sort_keys=True), file=sys.stderr, flush=True)


def current_run_id():
    evidence = _current.get()
    return evidence.run_id if evidence is not None else None
