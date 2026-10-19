"""Operation, confirmation and apply routes using factory-owned services."""
# Preserve existing handler signatures and explicit dependencies.
# pylint: disable=too-many-arguments,too-many-positional-arguments
from uuid import UUID

from fastapi import Request

from .apply_client import ApplyRequestError
from .auth import COOKIE
from .discovery_client import DiscoveryRequestError
from .dto import (
    ApplyRequestDTO, ApplyResultDTO, ConfirmationDTO, ConfirmationRequestDTO,
    DiscoveryResultDTO, SyncPlanDTO, SyncPlanRequestDTO,
)


def install_operation_routes(router, *, source_service, run_service,
                             discovery_client, apply_client, auth_client):
    """Register handlers in their original order under shared app boundaries."""
    def operation_view(value, source):
        from .operation_dto import OperationDTO  # pylint: disable=import-outside-toplevel
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
        return operation_view(
            discovery_client.start_operation(source_instance, 'DISCOVERY')['operation'], source_instance)

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
            except Exception:  # pylint: disable=broad-exception-caught
                # Never weaken the original fail-closed apply response on transport loss.
                pass

    @router.post('/sources/{source_instance}/sync-confirmations', response_model=ConfirmationDTO)
    def prepare_sync(source_instance: str, request: ConfirmationRequestDTO, http_request: Request):
        try:
            # Admission is this fresh server permission check, not possession of a plan.
            principal = auth_client.call(
                'authorize', session=http_request.cookies.get(COOKIE), permission='source.apply')
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
