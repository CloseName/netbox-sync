"""Closed diagnostics: no exception messages, request bodies or local variables."""
import json
from pathlib import Path
import re
import socket
import ssl

ERRORS=json.loads(Path(__file__).with_name('public_errors.json').read_text(encoding='utf-8'))


def classify(exc, stage):
    from .host_mapping import MappingError
    if isinstance(exc, MappingError):return 'MAPPING_INVALID'
    if getattr(exc,'code',None) in ERRORS:return exc.code
    from pynetbox.core.query import RequestError
    netbox=stage=='netbox' or isinstance(exc, RequestError)
    if isinstance(exc,socket.gaierror):return 'NETBOX_UNAVAILABLE' if netbox else 'SOURCE_DNS_FAILED'
    import requests
    if isinstance(exc,(ssl.SSLError,requests.exceptions.SSLError)):return 'NETBOX_TLS_FAILED' if netbox else 'SOURCE_TLS_FAILED'
    if isinstance(exc,(TimeoutError,requests.exceptions.Timeout)):return 'NETBOX_UNAVAILABLE' if netbox else 'SOURCE_TIMEOUT'
    if isinstance(exc,(ConnectionError,requests.exceptions.ConnectionError)):return 'NETBOX_UNAVAILABLE' if netbox else 'SOURCE_CONNECTION_FAILED'
    status=getattr(getattr(exc,'req',None),'status_code',getattr(exc,'status_code',None))
    if status in (401,403):return ('NETBOX_' if netbox else 'SOURCE_')+('AUTH_FAILED' if status==401 else 'PERMISSION_DENIED')
    if type(exc).__name__ in ('InvalidLogin','vim.fault.InvalidLogin'):return 'SOURCE_AUTH_FAILED'
    if type(exc).__name__ in ('NoPermission','vim.fault.NoPermission'):return 'SOURCE_PERMISSION_DENIED'
    return {'planning':'PLANNER_FAILED','provider':'PROVIDER_UNAVAILABLE','netbox':'NETBOX_UNAVAILABLE'}.get(stage,'DISCOVERY_FAILED')


def diagnostic(exc, stage):
    code=classify(exc,stage)
    # Only repository function names and line numbers, never traceback text/locals.
    frames=[];trace=exc.__traceback__;root=Path(__file__).parent.resolve()
    while trace:
        filename=Path(trace.tb_frame.f_code.co_filename).resolve()
        if filename.is_relative_to(root):
            name=trace.tb_frame.f_code.co_name
            if re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,80}',name):
                frames.append({'module':filename.stem,'function':name,'line':trace.tb_lineno})
        trace=trace.tb_next
    return {'code':code,'stage':ERRORS[code]['stage'],'frames':frames[-8:]}


class DiagnosticFailure(Exception):
    def __init__(self, exc, stage):
        self.diagnostic=diagnostic(exc,stage);self.code=self.diagnostic['code']
        super().__init__(self.code)


from contextlib import contextmanager

@contextmanager
def failure_stage(stage):
    try:yield
    except DiagnosticFailure:raise
    except Exception as exc:raise DiagnosticFailure(exc,stage) from None


def safe_diagnostic(value, code):
    code=code if code in ERRORS else 'OPERATION_FAILED'
    result={'code':code,'stage':ERRORS[code]['stage'],'frames':[]}
    if not isinstance(value,dict):return result
    frames=value.get('frames',[])
    if not isinstance(frames,list):return result
    for frame in frames[:8]:
        if (isinstance(frame,dict) and type(frame.get('line')) is int and 0<frame['line']<100000
            and all(isinstance(frame.get(k),str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,80}',frame[k]) for k in ('module','function'))):
            result['frames'].append({k:frame[k] for k in ('module','function','line')})
    return result
