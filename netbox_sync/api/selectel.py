"""Account inventory operations; credentials never enter response DTOs."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from .auth import COOKIE
from ..local_control import request as control


class Account(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account: str = Field(pattern=r'^[0-9]{1,20}$')
    name: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)


def routes(settings):
    router = APIRouter(prefix='/api/v1/selectel')

    def call(request, operation, data):
        result = control(settings.bootstrap_socket, dict(action='selectel', operation=operation,
            session=request.cookies.get(COOKIE), data=data), response_limit=2 * 1024 * 1024)['result']
        return JSONResponse(result, status_code=409 if result.get('error') else 200,
                            headers={'Cache-Control': 'no-store'})

    @router.get('')
    def accounts(request: Request):
        return call(request, 'list', {})

    @router.post('')
    def save(request: Request, payload: Account):
        data = payload.model_dump()
        data['password'] = payload.password.get_secret_value()
        return call(request, 'save', data)

    @router.post('/{account}/collect')
    def collect(request: Request, account: str):
        return call(request, 'collect', {'account': account})

    return router
