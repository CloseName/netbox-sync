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
from .onboarding_dto import ConnectionRequest, ConnectionResult, RegistrationRequest
from .onboarding_dto import CancellationRequest, CancellationResult
from .onboarding_adapters import BrokerSecretStore, RegistrationRegistry, test_esxi, test_proxmox
from .run_reader import PostgresRunReader
from .worker_health import WorkerHealthClient
from .lifecycle_client import LifecycleClient, LifecycleRequestError
from .operation_dto import LifecycleDTO, RemovalDTO
from .schedule_client import ScheduleRequestError, ScheduleWorkerClient

LOGGER = logging.getLogger('netbox_sync.api')


def _error(request, status, code, message):
    request.state.error_code = code
    dto = ErrorDTO(error=ErrorDetailDTO(code=code, message=message, request_id=request.state.request_id))
    return JSONResponse(status_code=status, content=dto.model_dump(mode='json'))


def _install_boundaries(app, settings):
    from ..local_control import ControlError

    @app.exception_handler(ControlError)
    async def control_error(request, exc):
        known = {'BOOTSTRAP_CONFLICT', 'BOOTSTRAP_NOT_READY', 'BOOTSTRAP_INVALID', 'BOOTSTRAP_BUSY', 'SOURCE_APPLY_ACTIVE'}
        return _error(request, 409 if exc.code in known else 503,
                      exc.code if exc.code in known else 'BOOTSTRAP_UNAVAILABLE',
                      'Reload bootstrap state and review before retrying')

    @app.exception_handler(LifecycleRequestError)
    async def lifecycle_error(request, exc):
        messages = {
            'SOURCE_NOT_FOUND': (404, 'Source not found'),
            'SOURCE_ALREADY_REMOVED': (409, 'Source is already removed'),
            'SOURCE_LIFECYCLE_CONFLICT': (409, 'Source changed; review its current state'),
            'SOURCE_CONFIRMATION_INVALID': (422, 'Enter the exact Source ID'),
            'SOURCE_OPERATION_ACTIVE': (409, 'Wait for active Plan or Discovery to finish'),
            'SOURCE_APPLY_ACTIVE': (409, 'Wait for active synchronization to finish'),
            'SOURCE_APPLY_UNCONFIRMED': (409, 'Synchronization outcome requires reconciliation'),
        }
        status, message = messages.get(exc.code, (503, 'Source lifecycle is unavailable; reload to check its state'))
        return _error(request, status, exc.code if exc.code in messages else 'LIFECYCLE_UNAVAILABLE', message)

    @app.exception_handler(OnboardingError)
    async def onboarding_error(request, exc):
        errors = {
            'SOURCE_ALREADY_EXISTS': (409, 'Source already exists'),
            'SOURCE_UNSUPPORTED': (422, 'Source type is unsupported'),
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
        }
        status, message = errors[exc.code.value]
        if getattr(exc, 'reserved_source_id', False):
            return _error(request, 409, 'SOURCE_ID_RESERVED',
                          'This Source ID was previously used and is reserved by a removed source.')
        return _error(request, status, exc.code.value, message)

    @app.exception_handler(SourceReadError)
    async def source_error(request, exc):
        errors = {
            'SOURCE_NOT_FOUND': (404, 'Source not found'),
            'SOURCE_DATA_INVALID': (503, 'Source metadata is unavailable'),
            'REGISTRY_UNAVAILABLE': (503, 'Source registry is unavailable'),
        }
        status, message = errors[exc.code.value]
        return _error(request, status, exc.code.value, message)

    @app.exception_handler(DiscoveryRequestError)
    async def discovery_error(request, exc):
        errors = {
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
        status, message = errors.get(exc.code, errors['DISCOVERY_UNAVAILABLE'])
        return _error(request, status, exc.code, message)

    @app.exception_handler(ApplyRequestError)
    async def apply_error(request, exc):
        statuses = {
            'SOURCE_NOT_FOUND': 404, 'SOURCE_DISABLED': 409, 'PLAN_BLOCKED': 409,
            'PLAN_STALE': 409, 'CONFIRMATION_INVALID': 409,
            'CONFIRMATION_EXPIRED': 409, 'CONFIRMATION_SOURCE_MISMATCH': 409,
            'APPLY_LOCKED': 409, 'OUTCOME_UNCERTAIN': 503,
        }
        return _error(request, statuses.get(exc.code, 503), exc.code, 'Manual sync request failed')

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
            if request.method in ('POST', 'PATCH') and (
                    request.url.path.startswith('/api/v1/bootstrap/') or request.url.path in (
                        '/api/v1/sources', '/api/v1/sources/test-connection',
                        '/api/v1/sources/cancel-onboarding',
                    ) or (
                        request.url.path.startswith('/api/v1/sources/')
                        and request.url.path.endswith(('/discovery', '/sync-plan',
                                                       '/sync-confirmations', '/sync', '/schedule',
                                                       '/operations/plan', '/operations/discovery', '/remove'))
                    )):
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
        return _error(request, 422, 'API_VALIDATION_FAILED', 'Request validation failed')


def create_app(settings=None, service=None, source_service=None, onboarding_service=None,
               discovery_client=None, apply_client=None, run_service=None,
               diagnostics_service=None, schedule_service=None):
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
    onboarding_service = onboarding_service or SourceOnboardingService(
        {'proxmox': partial(test_proxmox, policy=settings.egress_policy),
         'esxi': partial(test_esxi, policy=settings.egress_policy)}, EphemeralOnboardingStore(),
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
        settings.diagnostics_stale_seconds,
    )
    schedule_service = schedule_service or ScheduleService(
        source_service, PostgresRunReader(settings),
        ScheduleWorkerClient(settings.schedule_socket), settings.diagnostics_stale_seconds)
    app = FastAPI(title='NetBox Sync', version=application_version(),
                  docs_url=None, redoc_url=None, openapi_url=None, debug=False)
    _install_boundaries(app, settings)
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

    @router.get('/sources/{source_instance}/lifecycle', response_model=LifecycleDTO)
    def source_lifecycle(source_instance: str):
        return lifecycle_client.request(source_instance)

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
        return OperationDTO.model_validate(result)

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
    def prepare_sync(source_instance: str, request: ConfirmationRequestDTO):
        try:
            result = (apply_client.prepare(source_instance, request.plan_digest, str(request.operation_id))
                      if request.operation_id else apply_client.prepare(source_instance, request.plan_digest))
            return ConfirmationDTO.model_validate(result)
        except ApplyRequestError as exc:
            persist_stale(source_instance, request.operation_id, exc)
            raise

    @router.post('/sources/{source_instance}/sync', response_model=ApplyResultDTO)
    def apply_sync(source_instance: str, payload: ApplyRequestDTO, request: Request):
        try:
            result = ApplyResultDTO.model_validate(apply_client.apply(source_instance, payload.confirmation_token))
            request.state.run_id = str(result.run_id) if result.run_id else None
            return result
        except ApplyRequestError as exc:
            persist_stale(source_instance, payload.operation_id, exc)
            raise

    @router.post('/sources/test-connection', response_model=ConnectionResult)
    def connection_test(request: ConnectionRequest):
        token = onboarding_service.test_connection(request.credentials())
        return ConnectionResult(onboarding_token=token)

    @router.post('/sources', response_model=SourceDTO, status_code=201)
    def register_source(request: RegistrationRequest):
        onboarding_service.register(request.command())
        return SourceDTO.from_view(source_view({
            **request.model_dump(), 'enabled': True, 'sync_enabled': False, 'legacy_identity_owner': False,
        }))

    @router.post('/sources/cancel-onboarding', response_model=CancellationResult)
    def cancel_onboarding(request: CancellationRequest):
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
        @app.get('/diagnostics', include_in_schema=False)
        @app.get('/', include_in_schema=False)
        def frontend():
            return FileResponse(root / 'index.html')

    return app
