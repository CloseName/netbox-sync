"""pfSense access setup: password is forwarded once, never persisted by the API."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from ..local_control import request as control, ControlError
from .auth import COOKIE
from fastapi.responses import JSONResponse

class Connect(BaseModel):
    model_config = ConfigDict(extra='forbid')
    address: str = Field(min_length=1, max_length=253)
    port: int = Field(default=443, ge=1, le=65535)
    verify_tls: bool = True
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)
    policy_revision: int = Field(ge=0)

class Collect(BaseModel):
    model_config = ConfigDict(extra='forbid')
    policy_revision: int = Field(ge=0)

def routes(settings):
    router = APIRouter(prefix='/api/v1/pfsense')
    def call(vm_id, action, request, data=None):
        if not 0 < vm_id <= 2147483647: return JSONResponse({'error':'INVALID_VM'},status_code=400)
        try:
            result = control(settings.bootstrap_socket, dict(action='pfsense', operation=action,
                vm_id=vm_id, session=request.cookies.get(COOKIE), data=data or {}),timeout=125)['result']
        except ControlError as error:
            code=error.code if error.code in {'SOURCE_APPLY_ACTIVE','AUTH_DENIED','AUTH_REQUIRED','POLICY_CONFLICT','BOOTSTRAP_NOT_READY'} else 'OUTCOME_UNKNOWN'
            return JSONResponse({'error':code},status_code=503)
        return JSONResponse(result,status_code=409 if result.get('error') else 200)
    @router.get('/{vm_id}/status')
    def status(vm_id:int,request:Request): return call(vm_id,'status',request)
    @router.post('/{vm_id}/connect')
    def connect(vm_id:int,payload:Connect,request:Request):
        data=payload.model_dump();data['password']=payload.password.get_secret_value()
        return call(vm_id,'connect',request,data)
    @router.post('/{vm_id}/collect')
    def collect(vm_id:int,payload:Collect,request:Request): return call(vm_id,'collect',request,payload.model_dump())
    return router
