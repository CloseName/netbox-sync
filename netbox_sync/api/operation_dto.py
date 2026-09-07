"""Closed, credential-free latest-operation resources."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from .dto import SyncPlanDTO, DiscoveryResultDTO

class OperationDTO(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_id: UUID
    source_instance: str
    operation_kind: Literal['PLAN', 'DISCOVERY']
    status: Literal['RUNNING', 'READY', 'SUCCEEDED', 'FAILED', 'STALE']
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    safe_error_code: Literal['SOURCE_NOT_FOUND', 'SOURCE_DISABLED', 'CREDENTIAL_UNAVAILABLE',
        'REGISTRY_UNAVAILABLE', 'DISCOVERY_TIMEOUT', 'PROVIDER_UNAVAILABLE',
        'NETBOX_UNAVAILABLE', 'DISCOVERY_FAILED', 'RESULT_TOO_LARGE', 'RESULT_INVALID',
        'OPERATION_INTERRUPTED', 'OPERATION_FAILED', 'RESULT_EXPIRED', 'PLAN_STALE'] | None
    result: SyncPlanDTO | DiscoveryResultDTO | None

    @model_validator(mode='after')
    def coherent_result(self):
        success = self.status == ('READY' if self.operation_kind == 'PLAN' else 'SUCCEEDED')
        if (self.operation_kind == 'PLAN' and self.status == 'SUCCEEDED') or (self.operation_kind == 'DISCOVERY' and self.status in ('READY','STALE')):
            raise ValueError('Invalid operation status')
        expected = SyncPlanDTO if self.operation_kind == 'PLAN' else DiscoveryResultDTO
        if success:
            if not isinstance(self.result, expected) or self.result.source_instance != self.source_instance or self.finished_at is None or self.safe_error_code is not None:
                raise ValueError('Invalid operation result')
        elif self.result is not None:
            raise ValueError('Non-current result')
        if self.status == 'RUNNING' and (self.finished_at is not None or self.safe_error_code is not None):
            raise ValueError('Invalid active operation')
        return self


class LifecycleDTO(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_instance: str
    display_name: str
    removed_at: datetime | None
    credential_state: Literal['RETAINED_BY_REQUEST','REMOVED','RETAINED_SHARED_OR_LEGACY','CLEANUP_FAILED'] | None
    revision: str | None


class RemovalDTO(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirmed_source: str = Field(min_length=2, max_length=63)
    remove_credentials: StrictBool = False
