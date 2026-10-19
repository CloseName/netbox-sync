"""Read-only endpoint registration; application bootstrap and boundaries stay in app."""
# Keep the existing handler signatures and explicit factory dependencies.
# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
from uuid import UUID

from fastapi import Query, Request

from .dto import (
    DiagnosticsDTO, LivenessDTO, SourceDTO, SourceListDTO,
    SyncRunDTO, SyncRunListDTO, SystemHealthDTO, VersionDTO,
)


def install_read_routes(router, *, settings, service, diagnostics_service,
                        run_service, source_service, application_version):
    """Register on the existing router in order, using factory-owned dependencies.

    No connections or environment reads occur during registration. The version
    callable is evaluated on each request, as in the original factory closure.
    Authorization, request state and exception handling remain app-wide.
    """
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

    @router.get('/pfsense')
    def pfsense_list(offset: int = Query(default=0, ge=0, le=10000)):
        from .catalog import call  # pylint: disable=import-outside-toplevel
        return call(settings.bootstrap_socket, {'action':'pfsense-list', 'offset':offset})

    @router.get('/sources', response_model=SourceListDTO)
    def sources():
        return SourceListDTO(sources=[SourceDTO.from_view(view) for view in source_service.list_sources()])

    @router.get('/sources/{source_instance}', response_model=SourceDTO)
    def source_detail(source_instance: str):
        return SourceDTO.from_view(source_service.get_source(source_instance))
