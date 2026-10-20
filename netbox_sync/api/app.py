"""FastAPI factory with explicit read, registration, discovery, and sync boundaries."""

# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals

import logging
from functools import partial
from pathlib import Path

# Compatibility exports retained after staged extraction.
# pylint: disable-next=unused-import
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..application.health import SystemHealthService
from ..application.diagnostics import DiagnosticsService
from ..application.sources import SourceVisibilityService
from ..application.runs import RunHistoryService
from ..application.schedules import ScheduleService
from ..application.onboarding import EphemeralOnboardingStore, SourceOnboardingService
from .database import PostgresHealthProbe
from .read_routes import install_read_routes
from .lifecycle_routes import install_lifecycle_routes
from .schedule_routes import install_schedule_routes
from .operation_routes import install_operation_routes
from .catalog_routes import install_catalog_routes
from .onboarding_routes import install_onboarding_routes

# Compatibility exports retained after staged extraction.
# pylint: disable-next=unused-import
from .request_boundaries import _error, _install_boundaries, install_catalog_error_handler
from .settings import ApiSettings, application_version
from .lifecycle_adapters import ActiveSourceReader, LifecycleRegistrationRegistry
from .discovery_client import DiscoveryWorkerClient
from .apply_client import ApplyWorkerClient

# Compatibility exports retained after staged extraction.
# pylint: disable-next=unused-import
from .onboarding_adapters import BrokerSecretStore, RegistrationRegistry, test_esxi, test_proxmox
from .run_reader import PostgresRunReader
from .worker_health import WorkerHealthClient
from .lifecycle_client import LifecycleClient
from .auth import AuthClient, routes as auth_routes
from .schedule_client import ScheduleWorkerClient

LOGGER = logging.getLogger("netbox_sync.api")


def create_app(
    settings=None,
    service=None,
    source_service=None,
    onboarding_service=None,
    discovery_client=None,
    apply_client=None,
    run_service=None,
    diagnostics_service=None,
    schedule_service=None,
    auth_client=None,
):
    """Construct without DB access; all environment reading is confined to bootstrap."""
    if not LOGGER.handlers:
        LOGGER.addHandler(logging.StreamHandler())
    LOGGER.setLevel(logging.INFO)
    settings = settings or ApiSettings.from_environment()
    from .bootstrap import BootstrapClient

    def bootstrap_ready():
        return BootstrapClient(settings.bootstrap_socket).call("status").status == "READY"

    service = service or SystemHealthService(
        PostgresHealthProbe(settings),
        netbox_configured=bootstrap_ready if settings.bootstrap_socket else settings.netbox_configured,
    )
    source_service = source_service or SourceVisibilityService(ActiveSourceReader(settings))
    onboarding_injected = onboarding_service is not None
    onboarding_service = onboarding_service or SourceOnboardingService(
        {
            "proxmox": partial(test_proxmox, policy=settings.egress_policy, probe_socket=settings.probe_socket),
            "esxi": partial(test_esxi, policy=settings.egress_policy, probe_socket=settings.probe_socket),
        },
        EphemeralOnboardingStore(),
        LifecycleRegistrationRegistry(settings.registration_dsn, settings.registry_schema),
        BrokerSecretStore(settings.broker_socket),
    )
    discovery_client = discovery_client or DiscoveryWorkerClient(settings.discovery_socket)
    apply_client = apply_client or ApplyWorkerClient(settings.apply_socket)
    run_service = run_service or RunHistoryService(PostgresRunReader(settings))
    diagnostics_service = diagnostics_service or DiagnosticsService(
        source_service,
        PostgresRunReader(settings),
        WorkerHealthClient(settings.discovery_socket),
        WorkerHealthClient(settings.apply_socket),
        settings.diagnostics_stale_seconds,
        evidence_reader=LifecycleClient(settings.lifecycle_socket),
    )
    schedule_service = schedule_service or ScheduleService(
        source_service,
        PostgresRunReader(settings),
        ScheduleWorkerClient(settings.schedule_socket),
        settings.diagnostics_stale_seconds,
    )
    app = FastAPI(
        title="NetBox Sync", version=application_version(), docs_url=None, redoc_url=None, openapi_url=None, debug=False
    )
    auth_client = auth_client or AuthClient(settings.auth_socket)
    _install_boundaries(app, settings, auth_client)
    app.include_router(auth_routes(auth_client, source_service))
    router = APIRouter(prefix="/api/v1")

    install_read_routes(
        router,
        settings=settings,
        service=service,
        diagnostics_service=diagnostics_service,
        run_service=run_service,
        source_service=source_service,
        application_version=lambda: application_version(),
    )

    lifecycle_client = LifecycleClient(settings.lifecycle_socket)
    from .source_retirement import routes as retirement_routes

    app.include_router(retirement_routes(lifecycle_client))
    from .legacy_admission import routes as legacy_routes

    app.include_router(legacy_routes(settings, auth_client, lifecycle_client))
    from .source_recovery import routes as recovery_routes

    app.include_router(recovery_routes(settings, onboarding_service, auth_client, lifecycle_client, source_service))

    # Catalog helpers are bound later in this factory; resolve them per request.
    install_lifecycle_routes(
        router,
        settings=settings,
        lifecycle_client=lifecycle_client,
        catalog_validate=lambda *args, **kwargs: catalog_validate(*args, **kwargs),
    )
    install_schedule_routes(router, schedule_service=schedule_service)

    install_operation_routes(
        router,
        source_service=source_service,
        run_service=run_service,
        discovery_client=discovery_client,
        apply_client=apply_client,
        auth_client=auth_client,
    )

    from .catalog import call as catalog_call, validate as catalog_validate, create_call as catalog_create_call

    install_catalog_error_handler(app)

    install_catalog_routes(
        router, settings=settings, catalog_call=catalog_call, catalog_create_call=catalog_create_call
    )
    install_onboarding_routes(
        app,
        router,
        settings=settings,
        onboarding_service=onboarding_service,
        onboarding_injected=onboarding_injected,
        auth_client=auth_client,
        lifecycle_client=lifecycle_client,
        catalog_validate=catalog_validate,
        LOGGER=LOGGER,
    )

    if settings.bootstrap_socket:
        from .bootstrap import BootstrapClient, routes

        bootstrap_client = BootstrapClient(settings.bootstrap_socket)
        app.include_router(routes(bootstrap_client))
    from .pfsense import routes as pfsense_routes

    app.include_router(pfsense_routes(settings))
    from .selectel import routes as selectel_routes

    app.include_router(selectel_routes(settings))
    app.include_router(router)
    if settings.web_dist:
        root = Path(settings.web_dist)
        if not (root / "index.html").is_file() or not (root / "assets").is_dir():
            raise ValueError("Frontend build is unavailable")
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

        @app.get("/settings/netbox", include_in_schema=False)
        @app.get("/settings", include_in_schema=False)
        @app.get("/users", include_in_schema=False)
        @app.get("/policy", include_in_schema=False)
        @app.get("/setup", include_in_schema=False)
        @app.get("/sources", include_in_schema=False)
        @app.get("/sources/add", include_in_schema=False)
        @app.get("/sources/{source_instance}/sync", include_in_schema=False)
        @app.get("/sources/{source_instance}/runs", include_in_schema=False)
        @app.get("/sources/{source_instance}/schedule", include_in_schema=False)
        @app.get("/sources/{source_instance}/diagnostics", include_in_schema=False)
        @app.get("/sources/{source_instance}/configuration", include_in_schema=False)
        @app.get("/sources/{source_instance}", include_in_schema=False)
        @app.get("/runs", include_in_schema=False)
        @app.get("/runs/{run_id}", include_in_schema=False)
        @app.get("/system", include_in_schema=False)
        @app.get("/diagnostics", include_in_schema=False)
        @app.get("/", include_in_schema=False)
        def frontend():
            return FileResponse(root / "index.html")

    return app
