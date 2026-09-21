"""Closed, credential-free latest-operation resources."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator, field_validator
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
    safe_error_code: str | None
    diagnostic: dict | None = None
    used_run_id: UUID | None = None

    @field_validator('safe_error_code')
    @classmethod
    def known_error(cls,value):
        from ..worker_failure import ERRORS
        old={'SOURCE_NOT_FOUND','SOURCE_DISABLED','CREDENTIAL_UNAVAILABLE','REGISTRY_UNAVAILABLE',
             'RESULT_TOO_LARGE','RESULT_INVALID','OPERATION_INTERRUPTED','RESULT_EXPIRED','PLAN_STALE'}
        if value is not None and value not in set(ERRORS)|old:raise ValueError('Unknown error code')
        return value

    result: SyncPlanDTO | DiscoveryResultDTO | None

    @model_validator(mode='after')
    def coherent_result(self):
        from ..worker_failure import safe_diagnostic
        self.diagnostic = ({**safe_diagnostic(None,self.safe_error_code), 'event_id':str(self.operation_id)}
                           if self.status=='FAILED' else None)
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
    confirmed_source: str = Field(min_length=1, max_length=200)
    remove_credentials: StrictBool = True


class PlacementUpdateDTO(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    discovery_id: UUID
    references: dict[str, dict] = Field(max_length=5)
    host_types: dict[str, dict] = Field(max_length=16)


class SourceNameDTO(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    name: str = Field(min_length=1, max_length=200)
