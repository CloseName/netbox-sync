"""FastAPI factory with explicit read, registration, discovery, and sync boundaries."""
# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals

import json
import logging
from functools import partial
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from ..application.observability import ErrorCode
from ..application.health import SystemHealthService
from ..application.diagnostics import DiagnosticsService
from ..application.sources import SourceReadError, SourceVisibilityService
from ..application.sources import source_view
from ..application.runs import RunHistoryService, RunReadError
from ..application.schedules import ScheduleReadError, ScheduleService
from ..application.onboarding import EphemeralOnboardingStore, OnboardingError, SourceOnboardingService
from .database import PostgresHealthProbe
from .dto import (DiagnosticsDTO, ErrorDTO, ErrorDetailDTO, LivenessDTO,
                  SystemHealthDTO, VersionDTO)
from .settings import ApiSettings, application_version
from .lifecycle_adapters import ActiveSourceReader, LifecycleRegistrationRegistry
from .dto import (ApplyRequestDTO, ApplyResultDTO, ConfirmationDTO, ConfirmationRequestDTO,
                  DiscoveryResultDTO, ScheduleDTO, ScheduleUpdateDTO, SourceDTO,
                  SourceListDTO, SyncPlanDTO)
from .dto import SyncPlanRequestDTO, SyncRunDTO, SyncRunListDTO
from .discovery_client import DiscoveryRequestError, DiscoveryWorkerClient
from .apply_client import ApplyRequestError, ApplyWorkerClient
from .onboarding_dto import ConnectionRequest, ConnectionResult, RegistrationRequest, RegistrationStatusRequest, PlacementResolutionRequest
from .onboarding_dto import CancellationRequest, CancellationResult
from .onboarding_adapters import BrokerSecretStore, RegistrationRegistry, test_esxi, test_proxmox
from .run_reader import PostgresRunReader
from .worker_health import WorkerHealthClient
from .lifecycle_client import LifecycleClient, LifecycleRequestError
from .operation_dto import LifecycleDTO, RemovalDTO, SourceNameDTO
from .auth import AuthClient, COOKIE, PUBLIC, permission, routes as auth_routes
from ..auth_policy import AuthError
from .schedule_client import ScheduleRequestError, ScheduleWorkerClient

LOGGER = logging.getLogger('netbox_sync.api')


def _error(request, status, code, message, diagnostic=None):
    request.state.error_code = code
    from ..worker_failure import ERRORS
    detail=ERRORS.get(code)
    diagnostic = diagnostic or {}
    dto = ErrorDTO(error=ErrorDetailDTO(code=code, message=message, request_id=request.state.request_id,
        event_id=diagnostic.get('event_id') or request.state.request_id,stage=diagnostic.get('stage') or (detail['stage'] if detail else None),
        reason=diagnostic.get('reason'), difference_categories=diagnostic.get('categories', []),
        recommended_action=detail['action']['en'] if detail else None))
    content = dto.model_dump(mode='json')
    if not diagnostic:
        content['error'].pop('reason', None)
        content['error'].pop('difference_categories', None)
    return JSONResponse(status_code=status, content=content, headers={'Cache-Control':'no-store', 'X-Request-ID':request.state.request_id})


def _install_boundaries(app, settings, auth_client):
    from ..local_control import ControlError

    @app.exception_handler(AuthError)
    async def auth_error(request, exc):
        status = {'AUTH_REQUIRED':401, 'AUTH_REAUTH_REQUIRED':403, 'AUTH_DENIED':403, 'AUTH_INVALID':401,
                  'AUTH_RATE_LIMITED':429, 'ENROLLMENT_INVALID':409,
                  'POLICY_CONFLICT':409, 'POLICY_INVALID':422, 'TEAM_CONFLICT':409, 'TEAM_INVALID':422,
                  'POLICY_HOST_MANAGED':403, 'PROBE_RECEIPT_INVALID':409,
                  'LDAP_INVALID':422, 'LDAP_CONFLICT':409, 'LDAP_ACCESS_DENIED':403, 'LDAP_BIND_FAILED':422, 'LDAP_TLS_FAILED':422}.get(exc.code,503)
        return _error(request, status, exc.code, 'Authentication or policy request rejected')

    @app.exception_handler(ControlError)
    async def control_error(request, exc):
        known = {'BOOTSTRAP_CONFLICT', 'BOOTSTRAP_NOT_READY', 'BOOTSTRAP_INVALID', 'BOOTSTRAP_BUSY', 'SOURCE_APPLY_ACTIVE'}
        return _error(request, 409 if exc.code in known else 503,
                      exc.code if exc.code in known else 'BOOTSTRAP_UNAVAILABLE',
                      'Reload bootstrap state and review before retrying')

    @app.exception_handler(LifecycleRequestError)
    async def lifecycle_error(request, exc):
        messages = {
            'SOURCE_RECOVERY_NOT_REMOVED': (409, 'This source is active; open its existing page'),
            'SOURCE_IDENTITY_UNSUPPORTED': (409, 'This provider has no supported legacy hardware identity verification'),
            'SOURCE_IDENTITY_CHANGED': (409, 'Current hardware identity differs from the recorded source; do not reassign by address'),
            'SOURCE_IDENTITY_UNPROVED': (409, 'Fresh hardware evidence does not prove the historical NetBox source ownership'),
            'SOURCE_IDENTITY_CONFLICT': (409, 'Another retained source claims this hardware identity; administrator ownership review is required'),
            'SOURCE_RECOVERY_IDENTITY_REVIEW': (409, 'Hardware identity and original NetBox placement require administrator review'),
            'SOURCE_RECOVERY_IDENTITY_CONFLICT': (409, 'Another active source claims this host; recovery is blocked'),
            'SOURCE_RECOVERY_ACTIVE': (409, 'A recovery attempt already exists; reconcile that attempt'),
            'SOURCE_RECOVERY_NOT_FOUND': (404, 'Recovery attempt is unavailable for this user'),
            'SOURCE_RECOVERY_EVIDENCE_CHANGED': (409, 'Recovery evidence changed; review it again'),
            'SOURCE_RECOVERY_CREDENTIALS_UNCONFIRMED': (409, 'Credential ownership is unconfirmed; source remains removed'),
            'SOURCE_RECOVERY_OUTCOME_UNCERTAIN': (409, 'Credential creation may have started; automatic abandonment is forbidden'),
            'SOURCE_DISCOVERY_REQUIRED': (409, 'Run Discovery to refresh host mappings'),
            'SOURCE_NOT_FOUND': (404, 'Source not found'),
            'SOURCE_ALREADY_REMOVED': (409, 'Source is already removed'),
            'SOURCE_LIFECYCLE_CONFLICT': (409, 'Source changed; review its current state'),
            'SOURCE_CONFIRMATION_INVALID': (422, 'Enter the exact display name'),
            'SOURCE_OPERATION_ACTIVE': (409, 'Wait for active Plan or Discovery to finish'),
            'SOURCE_APPLY_ACTIVE': (409, 'Wait for active synchronization to finish'),
            'SOURCE_APPLY_UNCONFIRMED': (409, 'Synchronization outcome requires reconciliation'),
        }
        status, message = messages.get(exc.code, (503, 'Source lifecycle is unavailable; reload to check its state'))
        return _error(request, status, exc.code if exc.code in messages else 'LIFECYCLE_UNAVAILABLE', message)

    from ..host_registration import HostRegistrationConflict

    @app.exception_handler(HostRegistrationConflict)
    async def host_registration_error(request, exc):
        messages = {
            'HOST_REGISTRY_REVIEW_REQUIRED': 'An existing ESXi source lacks verified hardware identity. Administrator identity review is required before adding a host.',
            'HOST_REGISTRATION_INTENT_CHANGED': 'This attempt already started with different parameters. Restore the original confirmed parameters; do not create another source.',
            'HOST_REGISTRATION_INVALID': 'A stable registration request ID is required. Reload the registration form.',
            'HOST_IDENTITY_UNAVAILABLE': 'The provider did not supply a reliable hardware identity. Registration is blocked.',
            'HOST_SOURCE_REMOVED': 'This host belongs to a removed source. An administrator must review recovery of the original source.',
            'HOST_ALREADY_REGISTERED': 'This host already belongs to a source. Open that source; removed sources require administrator recovery.',
            'HOST_IDENTITY_CONFLICT': 'Several sources claim this host. Administrator reconciliation is required.',
            'HOST_REGISTRATION_RESERVED': 'An earlier registration reserved this host. Reconcile that attempt before registering again.',
        }
        request.state.error_code = exc.code
        existing = exc.source_instance if exc.code in {'HOST_ALREADY_REGISTERED','HOST_SOURCE_REMOVED','HOST_REGISTRY_REVIEW_REQUIRED'} else None
        return JSONResponse(status_code=409, content={'error': {
            'code': exc.code, 'message': messages[exc.code],
            'request_id': str(request.state.request_id),
            'existing_source': existing,
            'source_url': '/sources/' + existing if existing else None}})

    @app.exception_handler(OnboardingError)
    async def onboarding_error(request, exc):
        errors = {
            'SOURCE_ALREADY_EXISTS': (409, 'Source already exists'),
            'SOURCE_UNSUPPORTED': (422, 'Source type is unsupported'),
            'SOURCE_DNS_FAILED': (422, 'Source hostname could not be resolved'),
            'SOURCE_AUTH_FAILED': (422, 'Source authentication failed'),
            'SOURCE_TLS_FAILED': (422, 'Source TLS verification failed'),
            'SOURCE_TIMEOUT': (504, 'Source connection timed out'),
            'SOURCE_DESTINATION_DENIED': (422, 'Source destination is not permitted'),
            'SOURCE_CONNECTION_FAILED': (502, 'Source connection failed'),
            'ONBOARDING_TOKEN_INVALID': (409, 'Onboarding expired or already consumed; test again'),
            'SECRET_STORE_FAILED': (503, 'Protected secret storage is unavailable'),
            'REGISTRATION_UNAVAILABLE': (503, 'Registration is unavailable'),
            'REGISTRATION_FAILED': (503, 'Source registration failed'),
            'REGISTRATION_UNCERTAIN': (503, 'Registration outcome requires operator reconciliation'),
            'REGISTRATION_CLUSTER_RETAINED': (503, 'Cluster created; source registration requires reconciliation'),
        }
        status, message = errors[exc.code.value]
        if getattr(exc, 'reserved_source_id', False):
            return _error(request, 409, 'SOURCE_ID_RESERVED',
                          'This Source ID was previously used and is reserved by a removed source.')
        return _error(request, status, exc.code.value, message)

    @app.exception_handler(SourceReadError)
    async def source_error(request, exc):
        errors = {
            'SOURCE_DISCOVERY_REQUIRED': (409, 'Run Discovery to refresh host mappings'),
            'SOURCE_NOT_FOUND': (404, 'Source not found'),
            'SOURCE_DATA_INVALID': (503, 'Source metadata is unavailable'),
            'REGISTRY_UNAVAILABLE': (503, 'Source registry is unavailable'),
        }
        status, message = errors[exc.code.value]
        return _error(request, status, exc.code.value, message)

    @app.exception_handler(DiscoveryRequestError)
    async def discovery_error(request, exc):
        errors = {
            'SOURCE_DISCOVERY_REQUIRED': (409, 'Run Discovery to refresh host mappings'),
            'SOURCE_NOT_FOUND': (404, 'Source not found'),
            'SOURCE_DISABLED': (409, 'Disabled sources cannot be discovered'),
            'CREDENTIAL_UNAVAILABLE': (503, 'Discovery credentials are unavailable'),
            'REGISTRY_UNAVAILABLE': (503, 'Discovery registry is unavailable'),
            'DISCOVERY_TIMEOUT': (504, 'Discovery timed out'),
            'PROVIDER_UNAVAILABLE': (502, 'Source discovery failed'),
            'NETBOX_UNAVAILABLE': (502, 'NetBox comparison failed'),
            'DISCOVERY_FAILED': (502, 'Discovery failed'),
            'DISCOVERY_RESPONSE_INVALID': (502, 'Discovery returned an invalid response'),
            'DISCOVERY_UNAVAILABLE': (503, 'Discovery worker is unavailable'),
            'OPERATIONS_UNAVAILABLE': (503, 'Durable operations are unavailable'),
            'OPERATION_STILL_EXECUTING': (409, 'The operation is still executing'),
            'PLAN_STALE': (409, 'Plan is no longer current'),
        }
        from ..worker_failure import ERRORS
        status, message = errors.get(exc.code, (502, ERRORS[exc.code]['message']['en'])
                                     if exc.code in ERRORS else errors['DISCOVERY_UNAVAILABLE'])
        return _error(request, status, exc.code, message)

    @app.exception_handler(ApplyRequestError)
    async def apply_error(request, exc):
        statuses = {
            'SOURCE_NOT_FOUND': 404, 'SOURCE_DISABLED': 409, 'PLAN_BLOCKED': 409,
            'PLAN_STALE': 409, 'CONFIRMATION_INVALID': 409,
            'CONFIRMATION_EXPIRED': 409, 'CONFIRMATION_SOURCE_MISMATCH': 409,
            'APPLY_LOCKED': 409, 'OUTCOME_UNCERTAIN': 503,
        }
        diagnostic = dict(event_id=exc.event_id or request.state.request_id, reason=exc.reason, categories=exc.categories, stage='validation')
        LOGGER.warning(json.dumps(dict(component='api', code=exc.code, request_id=request.state.request_id, **diagnostic), sort_keys=True))
        return _error(request, statuses.get(exc.code, 503), exc.code, 'Manual sync request failed', diagnostic)

    @app.exception_handler(RunReadError)
    async def run_read_error(request, exc):
        errors = {
            'RUN_NOT_FOUND': (404, 'Synchronization run not found'),
            'RUN_FILTER_INVALID': (422, 'Synchronization history filter is invalid'),
            'RUN_HISTORY_UNAVAILABLE': (503, 'Synchronization history is unavailable'),
        }
        status, message = errors[exc.code.value]
        return _error(request, status, exc.code.value, message)

    @app.exception_handler(ScheduleRequestError)
    async def schedule_error(request, exc):
        errors = {
            'SCHEDULE_INVALID': (422, 'Scheduling settings are invalid'),
            'SCHEDULE_CONFLICT': (409, 'Scheduling settings changed; refresh and try again'),
            'SOURCE_DISCOVERY_REQUIRED': (409, 'Run Discovery to refresh host mappings'),
            'SOURCE_NOT_FOUND': (404, 'Source not found'),
            'CONTROL_WORKER_UNAVAILABLE': (503, 'Scheduling control is unavailable'),
            'CONTROL_REQUEST_FAILED': (503, 'Scheduling update failed'),
        }
        status, message = errors.get(exc.code, errors['CONTROL_REQUEST_FAILED'])
        return _error(request, status, exc.code, message)

    @app.exception_handler(ScheduleReadError)
    async def schedule_read_error(request, exc):
        return _error(request, 503, exc.code, 'Scheduling state is unavailable')

    @app.middleware('http')
    async def request_boundary(request: Request, call_next):
        # Never trust/re-emit client correlation headers, URLs, query or body.
        request.state.request_id = str(uuid4())
        request.state.error_code = None
        request.state.run_id = None
        request.state.diagnostics_status = None
        try:
            if settings.public_url:
                from ..tls_config import public_authority
                authority=public_authority(settings.public_url)
                local_health=(request.scope.get('client') is None and request.method=='GET'
                              and request.scope['path']=='/api/v1/health'
                              and request.headers.get('host')=='localhost')
                if not local_health:
                    # Uvicorn proxy middleware is disabled. Only the private Unix
                    # listener (client=None) may carry the proxy's canonical scheme.
                    if (request.scope.get('client') is not None
                            or request.headers.get('host')!=authority
                            or request.headers.get('x-forwarded-proto')!='https'):
                        return _error(request,403,'API_WRITE_FORBIDDEN','Public HTTPS boundary required')
                    request.scope['scheme']='https'
            if request.url.path.startswith('/api/v1/') and (request.method, request.url.path) not in PUBLIC:
                from starlette.concurrency import run_in_threadpool
                try:
                    request.state.principal = await run_in_threadpool(
                        auth_client.call, 'authorize', session=request.cookies.get(COOKIE),
                        audit=request.method not in ('GET','HEAD','OPTIONS'),
                        permission=('source.read' if permission(request.method, request.url.path)=='unmapped.deny'
                                    else permission(request.method, request.url.path)))
                    if permission(request.method, request.url.path)=='unmapped.deny':
                        known_path = request.url.path=='/api/v1/health' or any(
                            permission(method,request.url.path)!='unmapped.deny' for method in ('GET','POST','PATCH'))
                        return _error(request,405 if known_path else 404,
                            'API_METHOD_NOT_ALLOWED' if known_path else 'API_NOT_FOUND', 'Endpoint not available')
                except AuthError as exc:
                    return await auth_error(request, exc)
            if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.url.path.startswith('/api/v1/'):
                origin = urlsplit(request.headers.get('origin', ''))
                host = request.headers.get('host', '')
                if (host not in ((public_authority(settings.public_url),) if settings.public_url else settings.allowed_write_hosts) or origin.netloc != host
                        or origin.scheme != request.url.scheme or origin.path not in ('', '/')
                        or origin.query or origin.fragment or origin.username is not None
                        or request.headers.get('sec-fetch-site', 'same-origin') not in ('same-origin', 'none')
                        or request.headers.get('x-netbox-sync-csrf') != 'same-origin'
                        or request.headers.get('content-type', '').split(';')[0] != 'application/json'):
                    response = _error(request, 403, 'API_WRITE_FORBIDDEN', 'Same-origin write protection failed')
                elif (not request.headers.get('content-length', '').isdigit()
                      or int(request.headers['content-length']) > 16384):
                    response = _error(request, 413, 'API_REQUEST_TOO_LARGE', 'Request body is too large')
                else:
                    ready = True
                    if settings.bootstrap_socket and request.url.path.startswith('/api/v1/sources'):
                        from starlette.concurrency import run_in_threadpool
                        from .bootstrap import BootstrapClient
                        try:
                            state = await run_in_threadpool(BootstrapClient(settings.bootstrap_socket).call, 'status')
                            ready = state.status == 'READY'
                        except Exception:
                            ready = False
                    response = await call_next(request) if ready else _error(request, 409, 'BOOTSTRAP_NOT_READY', 'Complete NetBox setup first')
            else:
                response = await call_next(request)
        except Exception:  # pylint: disable=broad-exception-caught
            response = _error(request, 500, 'API_INTERNAL_ERROR', 'API request failed')
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        LOGGER.log(logging.ERROR if response.status_code >= 500 else logging.INFO, json.dumps({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': 'ERROR' if response.status_code >= 500 else 'INFO',
            'component': 'api',
            'request_id': request.state.request_id,
            'run_id': request.state.run_id,
            'actor_id': getattr(request.state, 'principal', {}).get('principal_id'),
            'source_instance': None,
            'error_code': request.state.error_code,
            'message': 'HTTP request completed',
            'status_code': response.status_code,
            'diagnostics_status': request.state.diagnostics_status,
        }))
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        codes = {404: ('API_NOT_FOUND', 'Endpoint not found'),
                 405: ('API_METHOD_NOT_ALLOWED', 'Method not allowed')}
        code, message = codes.get(exc.status_code, ('API_REQUEST_FAILED', 'Request rejected'))
        return _error(request, exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, _exc):
        if request.url.path == '/api/v1/sources/test-connection' and any(error.get('loc') == ('body', 'address') for error in _exc.errors()):
            return _error(request, 422, 'SOURCE_ADDRESS_INVALID', 'Use a bare hostname or IPv4 address')
        return _error(request, 422, 'API_VALIDATION_FAILED', 'Request validation failed')


def create_app(settings=None, service=None, source_service=None, onboarding_service=None,
               discovery_client=None, apply_client=None, run_service=None,
               diagnostics_service=None, schedule_service=None, auth_client=None):
    """Construct without DB access; all environment reading is confined to bootstrap."""
    if not LOGGER.handlers:
        LOGGER.addHandler(logging.StreamHandler())
    LOGGER.setLevel(logging.INFO)
    settings = settings or ApiSettings.from_environment()
    from .bootstrap import BootstrapClient
    def bootstrap_ready():
        return BootstrapClient(settings.bootstrap_socket).call('status').status == 'READY'

    service = service or SystemHealthService(
        PostgresHealthProbe(settings), netbox_configured=bootstrap_ready if settings.bootstrap_socket else settings.netbox_configured,
    )
    source_service = source_service or SourceVisibilityService(ActiveSourceReader(settings))
    onboarding_injected = onboarding_service is not None
    onboarding_service = onboarding_service or SourceOnboardingService(
        {'proxmox': partial(test_proxmox, policy=settings.egress_policy, probe_socket=settings.probe_socket),
         'esxi': partial(test_esxi, policy=settings.egress_policy, probe_socket=settings.probe_socket)}, EphemeralOnboardingStore(),
        LifecycleRegistrationRegistry(settings.registration_dsn, settings.registry_schema),
        BrokerSecretStore(settings.broker_socket),
    )
    discovery_client = discovery_client or DiscoveryWorkerClient(settings.discovery_socket)
    apply_client = apply_client or ApplyWorkerClient(settings.apply_socket)
    run_service = run_service or RunHistoryService(PostgresRunReader(settings))
    diagnostics_service = diagnostics_service or DiagnosticsService(
        source_service, PostgresRunReader(settings),
        WorkerHealthClient(settings.discovery_socket),
        WorkerHealthClient(settings.apply_socket),
        settings.diagnostics_stale_seconds, evidence_reader=LifecycleClient(settings.lifecycle_socket),
    )
    schedule_service = schedule_service or ScheduleService(
        source_service, PostgresRunReader(settings),
        ScheduleWorkerClient(settings.schedule_socket), settings.diagnostics_stale_seconds)
    app = FastAPI(title='NetBox Sync', version=application_version(),
                  docs_url=None, redoc_url=None, openapi_url=None, debug=False)
    auth_client = auth_client or AuthClient(settings.auth_socket)
    _install_boundaries(app, settings, auth_client)
    app.include_router(auth_routes(auth_client,source_service))
    router = APIRouter(prefix='/api/v1')

    @router.get('/health', response_model=LivenessDTO)
    def health():
        return LivenessDTO()

    @router.get('/system/health', response_model=SystemHealthDTO)
    def system_health():
        return SystemHealthDTO.from_result(service.check())

    @router.get('/diagnostics', response_model=DiagnosticsDTO)
    def diagnostics(request: Request):
        result = diagnostics_service.check()
        request.state.diagnostics_status = result.overall_status.value
        return DiagnosticsDTO.from_result(result)

    @router.get('/version', response_model=VersionDTO)
    def version():
        return VersionDTO(version=application_version())

    @router.get('/runs', response_model=SyncRunListDTO)
    def runs(source_instance: str | None = None, source_type: str | None = None,
             trigger: str | None = None, status: str | None = None,
             limit: int = Query(default=50), cursor: str | None = None):
        records = run_service.list_runs(
            source_instance=source_instance, source_type=source_type, trigger=trigger,
            status=status, limit=limit, cursor=cursor,
        )
        return SyncRunListDTO(
            runs=[SyncRunDTO.from_record(record) for record in records],
            next_cursor=str(records[-1].run_id) if len(records) == limit else None,
        )

    @router.get('/runs/{run_id}', response_model=SyncRunDTO)
    def run_detail(run_id: UUID, request: Request):
        request.state.run_id = str(run_id)
        return SyncRunDTO.from_record(run_service.get_run(run_id))

    @router.get('/sources', response_model=SourceListDTO)
    def sources():
        return SourceListDTO(sources=[SourceDTO.from_view(view) for view in source_service.list_sources()])

    @router.get('/sources/{source_instance}', response_model=SourceDTO)
    def source_detail(source_instance: str):
        return SourceDTO.from_view(source_service.get_source(source_instance))

    lifecycle_client = LifecycleClient(settings.lifecycle_socket)
    from .source_recovery import routes as recovery_routes
    app.include_router(recovery_routes(settings,onboarding_service,auth_client,lifecycle_client,source_service))

    @router.get('/sources/{source_instance}/lifecycle', response_model=LifecycleDTO)
    def source_lifecycle(source_instance: str):
        return lifecycle_client.request(source_instance)

    from .operation_dto import PlacementUpdateDTO

    @router.get('/sources/{source_instance}/placement')
    def source_placement(source_instance: str):
        return lifecycle_client.placement(source_instance)

    @router.patch('/sources/{source_instance}/placement', response_model=LifecycleDTO)
    def update_source_placement(source_instance: str, payload: PlacementUpdateDTO):
        current = lifecycle_client.placement(source_instance)
        if current['revision'] != payload.revision or current['discovery_id'] != str(payload.discovery_id):
            raise LifecycleRequestError('SOURCE_LIFECYCLE_CONFLICT')
        mapping = catalog_validate(settings.bootstrap_socket, payload.references, payload.host_types, current['preview'])
        if payload.ip_conflict_policy is not None:
            mapping['ip_conflict_policy'] = payload.ip_conflict_policy
        if payload.network_scope_rules is not None:
            from .catalog import call
            mapping['network_scope_rules']=call(settings.bootstrap_socket,{'action':'validate-scopes','rules':payload.network_scope_rules})['rules']
        return lifecycle_client.request(source_instance, dict(revision=payload.revision,
            discovery_id=str(payload.discovery_id), mapping=mapping), action='save_placement')

    @router.patch('/sources/{source_instance}/name', response_model=LifecycleDTO)
    def rename_source(source_instance: str, payload: SourceNameDTO):
        return lifecycle_client.request(source_instance, payload.model_dump(), action='rename_source')

    @router.post('/sources/{source_instance}/remove', response_model=LifecycleDTO)
    def remove_source(source_instance: str, payload: RemovalDTO):
        return lifecycle_client.request(source_instance, payload.model_dump())

    @router.get('/sources/{source_instance}/schedule', response_model=ScheduleDTO)
    def source_schedule(source_instance: str):
        return ScheduleDTO.from_view(schedule_service.get(source_instance))

    @router.patch('/sources/{source_instance}/schedule', response_model=ScheduleDTO)
    def update_source_schedule(source_instance: str, payload: ScheduleUpdateDTO):
        return ScheduleDTO.from_view(schedule_service.update(
            source_instance, payload.model_dump()))

    def operation_view(value, source):
        from .operation_dto import OperationDTO
        result = dict(value)
        if result.get('source_instance') != source:
            raise DiscoveryRequestError('DISCOVERY_RESPONSE_INVALID')
        if result.get('result') is not None and result['result'].get('source_instance') != source:
            raise DiscoveryRequestError('DISCOVERY_RESPONSE_INVALID')
        if result.get('result') is not None:
            dto = SyncPlanDTO if result['operation_kind'] == 'PLAN' else DiscoveryResultDTO
            result['result'] = dto.from_worker(result['result']).model_dump(mode='json')
        dto = OperationDTO.model_validate(result)
        if dto.operation_kind == 'PLAN' and dto.status == 'READY':
            used = run_service.plan_run(source, dto.result.digest, dto.finished_at)
            dto.used_run_id = UUID(used) if used else None
        return dto

    @router.get('/sources/{source_instance}/operations')
    def source_operations(source_instance: str):
        source_service.get_source(source_instance)
        return {'operations': [operation_view(value, source_instance) for value in
                               discovery_client.operations(source_instance)['operations']]}

    @router.post('/sources/{source_instance}/operations/plan', status_code=202)
    def start_plan(source_instance: str, _request: SyncPlanRequestDTO):
        source_service.get_source(source_instance)
        return operation_view(discovery_client.start_operation(source_instance, 'PLAN')['operation'], source_instance)

    @router.post('/sources/{source_instance}/operations/discovery', status_code=202)
    def start_discovery(source_instance: str, _request: SyncPlanRequestDTO):
        source_service.get_source(source_instance)
        return operation_view(discovery_client.start_operation(source_instance, 'DISCOVERY')['operation'], source_instance)

    @router.post('/sources/{source_instance}/discovery', response_model=DiscoveryResultDTO)
    def discover_source(source_instance: str):
        result = DiscoveryResultDTO.from_worker(discovery_client.discover(source_instance))
        if result.source_instance != source_instance:
            raise DiscoveryRequestError('DISCOVERY_RESPONSE_INVALID')
        return result

    @router.post('/sources/{source_instance}/sync-plan', response_model=SyncPlanDTO)
    def sync_plan(source_instance: str, _request: SyncPlanRequestDTO):
        result = SyncPlanDTO.from_worker(discovery_client.plan(source_instance))
        if result.source_instance != source_instance:
            raise DiscoveryRequestError('DISCOVERY_RESPONSE_INVALID')
        return result

    def persist_stale(source, operation_id, error):
        if error.code == 'PLAN_STALE' and operation_id is not None:
            try:
                discovery_client.invalidate_plan(source, operation_id)
            except Exception:
                # Never weaken the original fail-closed apply response on transport loss.
                pass

    @router.post('/sources/{source_instance}/sync-confirmations', response_model=ConfirmationDTO)
    def prepare_sync(source_instance: str, request: ConfirmationRequestDTO, http_request: Request):
        try:
            # Admission is this fresh server permission check, not possession of a plan.
            principal = auth_client.call('authorize', session=http_request.cookies.get(COOKIE), permission='source.apply')
            result = apply_client.prepare(source_instance, request.plan_digest,
                **({'operation_id': str(request.operation_id)} if request.operation_id else {}),
                actor_id=principal['principal_id'])
            return ConfirmationDTO.model_validate(result)
        except ApplyRequestError as exc:
            persist_stale(source_instance, request.operation_id, exc)
            raise

    @router.post('/sources/{source_instance}/sync', response_model=ApplyResultDTO)
    def apply_sync(source_instance: str, payload: ApplyRequestDTO, request: Request):
        try:
            principal = auth_client.call('authorize', session=request.cookies.get(COOKIE), permission='source.apply')
            result = ApplyResultDTO.model_validate(apply_client.apply(source_instance, payload.confirmation_token,
                actor_id=principal['principal_id'], **({'run_id':str(payload.run_id)} if payload.run_id else {})))
            request.state.run_id = str(result.run_id) if result.run_id else None
            return result
        except ApplyRequestError as exc:
            persist_stale(source_instance, payload.operation_id, exc)
            raise

    from .catalog import CatalogError, call as catalog_call, validate as catalog_validate, create_call as catalog_create_call

    @app.exception_handler(CatalogError)
    async def catalog_error(request,exc):
        known={'BUSY','CONFLICT','CATALOG_CHANGED','SELECTION_REQUIRED','HOST_MAPPING_REQUIRED','CLUSTER_SCOPE_MISMATCH','CLUSTER_AMBIGUOUS','CLUSTER_REVIEW_REQUIRED','PERMISSION_DENIED','AUTH_FAILED','TLS_FAILED','NETWORK_UNREACHABLE','RESPONSE_INVALID','UNAVAILABLE'}
        code=exc.code if exc.code in known else 'UNAVAILABLE'
        status=409 if code in {'BUSY','CONFLICT','CATALOG_CHANGED','SELECTION_REQUIRED','HOST_MAPPING_REQUIRED','CLUSTER_SCOPE_MISMATCH','CLUSTER_AMBIGUOUS','CLUSTER_REVIEW_REQUIRED'} else 503
        return _error(request,status,'CATALOG_'+code.removeprefix('CATALOG_'),'NetBox selection could not be verified')

    from .catalog_dto import CatalogCreateDTO

    @router.post('/catalog/{kind}')
    def create_catalog(kind: str, payload: CatalogCreateDTO):
        return catalog_create_call(settings.bootstrap_socket,dict(action='catalog-create',
            operation_id=str(payload.operation_id),kind=kind,object=payload.object,
            write_token=payload.write_token.get_secret_value(),confirm=payload.confirm))

    @router.get('/catalog-operations/{operation_id}')
    def reconcile_catalog(operation_id: UUID):
        return catalog_create_call(settings.bootstrap_socket,dict(action='catalog-reconcile',operation_id=str(operation_id)))

    @router.get('/catalog/{kind}')
    def catalog(kind: str, search: str = Query(default='',max_length=100), offset: int = Query(default=0,ge=0,le=10000)):
        from ..netbox_catalog import ENDPOINTS
        if kind not in ENDPOINTS: raise CatalogError('SELECTION_REQUIRED')
        return catalog_call(settings.bootstrap_socket,{'action':'list','kind':kind,'search':search,'offset':offset})

    from .onboarding_dto import DestinationRequest

    @router.post('/sources/check-destination')
    def check_destination(payload: DestinationRequest, http: Request):
        from ..application.onboarding import PendingCredentials
        from ..probe_worker import remote_test_authorized
        session=http.cookies.get(COOKIE)
        policy=auth_client.call('probe.policy',session=session)
        if not settings.probe_socket: raise AuthError('AUTH_UNAVAILABLE')
        remote_test_authorized(settings.probe_socket,
            PendingCredentials(payload.source_type,payload.address,True,'','','',port=payload.port),
            session,policy['revision'],destination_only=True)
        return {'allowed': True}

    @router.post('/sources/test-connection', response_model=ConnectionResult)
    def connection_test(request: ConnectionRequest, http: Request):
        session = http.cookies.get(COOKIE)
        policy = auth_client.call('probe.policy', session=session)
        from ..probe_worker import remote_test_authorized
        preview=None
        recovery_meta=None
        if request.recovery_source:
            auth_client.call('authorize',session=session,permission='source.remove')
            if request.source_type!='esxi':raise LifecycleRequestError('SOURCE_RECOVERY_IDENTITY_REVIEW')
            recovery_meta=lifecycle_client.recovery('describe',request.recovery_source,
                actor_id=http.state.principal['principal_id'])
        if settings.probe_socket:
            preview=remote_test_authorized(settings.probe_socket, request.credentials(), session, policy['revision'], **({'preview':True} if request.preview or request.source_type == 'esxi' else {}))
            if request.registration_resume:
                token=onboarding_service.accept_registration_resume(request.credentials(),preview,
                    request.registration_resume.source_instance,request.registration_resume.registration_id,
                    http.state.principal['principal_id'])
            else:
                token = (onboarding_service.accept_recovery_credentials(request.credentials(),preview,
                    request.recovery_source,recovery_meta['host_uuid']) if recovery_meta else
                    onboarding_service.accept_checked_credentials(request.credentials(), preview))
        elif onboarding_injected and not request.recovery_source and not request.registration_resume:
            token = onboarding_service.test_connection(request.credentials())
        else:
            # Explicit in-process adapter injection is only for tests. Production
            # has a required remote probe; no API egress fallback.
            raise AuthError('AUTH_UNAVAILABLE')
        try:
            auth_client.call('receipt.issue', session=session, receipt=token,
                             destination=request.address, provider=request.source_type, revision=policy['revision'])
        except AuthError:
            onboarding_service.cancel(token)
            raise
        return ConnectionResult(onboarding_token=token,preview=preview,suggested_source_instance=request.registration_resume.source_instance if request.registration_resume else request.source_type+'-'+uuid4().hex[:20])

    from .onboarding_dto import PlacementReviewRequest

    @router.post('/sources/review-placement')
    def review_placement(payload: PlacementReviewRequest, http: Request):
        auth_client.call('receipt.check', session=http.cookies.get(COOKIE), receipt=payload.onboarding_token)
        catalog_validate(settings.bootstrap_socket, payload.references, payload.host_types,
                         onboarding_service.preview(payload.onboarding_token), pending_cluster=payload.create_cluster)
        return {'valid': True}

    @router.post('/sources/resolve-placement')
    def resolve_placement(payload: PlacementResolutionRequest, http: Request):
        from .catalog import call
        auth_client.call('receipt.check',session=http.cookies.get(COOKIE),receipt=payload.onboarding_token)
        preview=onboarding_service.preview(payload.onboarding_token)
        if not preview:raise CatalogError('SELECTION_REQUIRED')
        return call(settings.bootstrap_socket,dict(action='resolve-placement',provider=preview['provider'],
            hosts=preview['hosts'],name=payload.name,site_id=payload.site_id,default_site_slug=settings.default_site_slug))

    @router.post('/sources', response_model=SourceDTO, status_code=201)
    def register_source(request: RegistrationRequest, http: Request):
        from dataclasses import replace
        mapping={}
        fingerprint=request.intent_fingerprint()
        def bind_intent():
            return onboarding_service.registration_intent(request.command(),request.registration_id,
                http.state.principal['principal_id'],fingerprint)
        # Reserve before catalog POSTs or filesystem credentials. The actor/nonce
        # binding survives response loss and cannot be claimed by another request.
        auth_client.call('receipt.check', session=http.cookies.get(COOKIE), receipt=request.onboarding_token)
        onboarding_service.reserve_provider_identity(request.command(), request.registration_id,
                                                      http.state.principal['principal_id'])
        with onboarding_service.registration_guard(request.command(), request.registration_id,
                                                    http.state.principal['principal_id']):
            if request.automatic_placement:
                from .catalog import call
                auth_client.call('receipt.check',session=http.cookies.get(COOKIE),receipt=request.onboarding_token)
                onboarding_service.check_registration(request.command())
                preview=onboarding_service.preview(request.onboarding_token)
                if not preview or not request.registration_id:raise CatalogError('SELECTION_REQUIRED')
                resolved=call(settings.bootstrap_socket,dict(action='resolve-placement',provider=request.source_type,
                    hosts=preview['hosts'],name=request.name,site_id=(request.references.get('site') or {}).get('id'),
                    default_site_slug=settings.default_site_slug))
                if resolved['issues']:raise CatalogError('CLUSTER_REVIEW_REQUIRED' if any(i['kind']=='cluster' for i in resolved['issues']) else 'SELECTION_REQUIRED')
                request=request.model_copy(update={'references':resolved['references'],'host_types':resolved['host_types'],
                    'create_cluster':resolved['create_cluster'],'cluster_name':request.name})
            if request.create_cluster:
                # Authorize the exact receipt before starting any optional remote write.
                from uuid import UUID, uuid5
                from .catalog import create_call
                auth_client.call('receipt.check', session=http.cookies.get(COOKIE), receipt=request.onboarding_token)
                onboarding_service.check_registration(request.command())
                pending=catalog_validate(settings.bootstrap_socket, request.references, request.host_types,
                    onboarding_service.preview(request.onboarding_token), pending_cluster=True)
                operation_id=str(uuid5(UUID('b6c311eb-0d55-45af-80a5-b949a20bfe47'),
                    http.state.principal['principal_id']+':'+request.source_instance+':'+str(request.registration_id)))
                bind_intent()
                try:
                    outcome=create_call(settings.bootstrap_socket, dict(action='registration-cluster',
                        operation_id=operation_id, name=request.name,
                        site_id=pending['references']['site']['id'],
                        cluster_type_id=pending['references']['cluster_type']['id']))
                except CatalogError as exc:
                    if exc.code=='UNAVAILABLE':
                        raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN) from None
                    raise
                if outcome.get('status')=='UNCERTAIN':
                    raise OnboardingError(ErrorCode.REGISTRATION_UNCERTAIN)
                if outcome.get('status')=='REFUSED':
                    raise CatalogError(outcome.get('error','SELECTION_REQUIRED'))
                if outcome.get('status')!='CREATED' or not outcome.get('item'):
                    raise CatalogError('CLUSTER_REVIEW_REQUIRED')
                request=request.model_copy(update={'references':{**pending['references'],'cluster':outcome['item']}})
            try:
                if request.references or request.host_types or onboarding_service.preview(request.onboarding_token):
                    mapping=catalog_validate(settings.bootstrap_socket,request.references,request.host_types,onboarding_service.preview(request.onboarding_token),require_empty_cluster=True)
                    refs=mapping['references'];types=mapping['host_types']
                    if refs['cluster']['name']!=request.name:raise CatalogError('CLUSTER_REVIEW_REQUIRED')
                    request=request.model_copy(update={'site_slug':refs['site']['slug'],'cluster_name':refs['cluster']['name'],
                        'platform_slug':refs['platform']['slug'],'device_role_slug':refs['device_role']['slug'],
                        'cluster_type_slug':refs['cluster_type']['slug'],'device_type_slug':next(iter(types.values()))['slug']})
                elif not onboarding_injected:
                    raise CatalogError('SELECTION_REQUIRED')
                registration=bind_intent()
                auth_client.call('receipt.consume', session=http.cookies.get(COOKIE),
                                 receipt=request.onboarding_token, destination=request.address, provider=request.source_type)
                onboarding_service.register(replace(request.command(),mapping=mapping),registration=registration)
                return SourceDTO.from_view(source_view({
                    **request.model_dump(), 'enabled': True, 'sync_enabled': False, 'legacy_identity_owner': False,
                }))
            except Exception:
                if request.create_cluster:
                    # The durable catalog journal records the created cluster. Never
                    # delete it on registry/secret/receipt failure or claim no writes.
                    raise OnboardingError(ErrorCode.REGISTRATION_CLUSTER_RETAINED) from None
                raise

    @router.post('/sources/registration-status')
    def registration_status(request: RegistrationStatusRequest, http: Request):
        # The browser never chooses a raw privileged catalog journal ID. Its
        # registration nonce is bound to the authenticated actor and source.
        identity = onboarding_service.registration_outcome(request.source_instance,
            request.registration_id, http.state.principal['principal_id'])
        if identity['identity_status'] == 'REGISTERED':
            return {**identity, 'status': 'REGISTERED'}
        if identity['identity_status']=='OUTCOME_UNCERTAIN':
            return {**identity,'status':'UNCERTAIN','resume_supported':True}
        if identity['identity_status'] in {'RESTORE_REQUIRED', 'IDENTITY_CONFLICT'}:
            return {**identity, 'status': 'UNCERTAIN'}
        from uuid import uuid5
        from .catalog import create_call
        operation_id=str(uuid5(UUID('b6c311eb-0d55-45af-80a5-b949a20bfe47'),
            http.state.principal['principal_id']+':'+request.source_instance+':'+str(request.registration_id)))
        result=create_call(settings.bootstrap_socket,dict(action='catalog-reconcile',operation_id=operation_id))
        return {'status':result.get('status') if result.get('status') in
                {'CREATED','REFUSED','UNCERTAIN','EXISTS_REVIEW_REQUIRED'} else 'UNCERTAIN'}

    @router.post('/sources/cancel-onboarding', response_model=CancellationResult)
    def cancel_onboarding(request: CancellationRequest, http: Request):
        auth_client.call('receipt.cancel', session=http.cookies.get(COOKIE), receipt=request.onboarding_token)
        onboarding_service.cancel(request.onboarding_token)
        return CancellationResult()

    if settings.bootstrap_socket:
        from .bootstrap import BootstrapClient, routes
        bootstrap_client = BootstrapClient(settings.bootstrap_socket)
        app.include_router(routes(bootstrap_client))
    app.include_router(router)
    if settings.web_dist:
        root = Path(settings.web_dist)
        if not (root / 'index.html').is_file() or not (root / 'assets').is_dir():
            raise ValueError('Frontend build is unavailable')
        app.mount('/assets', StaticFiles(directory=root / 'assets'), name='assets')

        @app.get('/settings/netbox', include_in_schema=False)
        @app.get('/settings', include_in_schema=False)
        @app.get('/policy', include_in_schema=False)
        @app.get('/setup', include_in_schema=False)
        @app.get('/sources', include_in_schema=False)
        @app.get('/sources/add', include_in_schema=False)
        @app.get('/sources/{source_instance}/sync', include_in_schema=False)
        @app.get('/sources/{source_instance}/runs', include_in_schema=False)
        @app.get('/sources/{source_instance}/schedule', include_in_schema=False)
        @app.get('/sources/{source_instance}/diagnostics', include_in_schema=False)
        @app.get('/sources/{source_instance}/configuration', include_in_schema=False)
        @app.get('/sources/{source_instance}', include_in_schema=False)
        @app.get('/runs', include_in_schema=False)
        @app.get('/runs/{run_id}', include_in_schema=False)
        @app.get('/system', include_in_schema=False)
        @app.get('/diagnostics', include_in_schema=False)
        @app.get('/', include_in_schema=False)
        def frontend():
            return FileResponse(root / 'index.html')

    return app
