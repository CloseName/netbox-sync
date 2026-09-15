"""Scheduled failure records never expose remote text, credentials or arbitrary URLs."""
import json
from types import SimpleNamespace
from uuid import uuid4
import pytest
import requests
from pynetbox.core.query import RequestError
from netbox_sync import scheduled_failure as diagnostics
from netbox_sync.orchestrator import run_sources
from tests.test_orchestrator import source, RunRecorder


def error(status=403, url='https://operator:PRIVATE@netbox.invalid/api/dcim/devices/?secret=PRIVATE'):
    response=requests.Response()
    response.status_code=status;response._content=b'{"secret":"PRIVATE"}'
    response.request=requests.Request('GET',url,headers={'Authorization':'PRIVATE'}).prepare()
    return RequestError(response)


def test_correlated_diagnostic_and_failed_run_keep_computed_plan(capsys):
    run_id=uuid4()
    history=RunRecorder()
    history.start_run=lambda *args: SimpleNamespace(run_id=run_id)
    def execute(_source):
        diagnostics.mark('planning')
        diagnostics.mark('apply',SimpleNamespace(digest='a'*64,planner_version='reviewed'))
        raise error()
    result=run_sources([source('pve-a')],execute,run_repository=history)
    captured=capsys.readouterr()
    value=json.loads(captured.err)
    assert value['run_id']==str(run_id) and value['stage']=='apply'
    assert value['write_outcome']=='MAY_HAVE_WRITTEN'
    assert value['exception_class']=='RequestError'
    assert value['http']=={'status':403,'method':'GET','endpoint':'dcim.devices'}
    assert value['frames'] and set(value['frames'][0])=={'module','function','line'}
    assert not any(s in captured.err+repr(result)+repr(history.finished) for s in ('PRIVATE','netbox.invalid','Authorization'))
    assert history.finished[0][2]['plan_digest']=='a'*64
    assert history.finished[0][2]['planner_version']=='reviewed'
    assert history.finished[0][1].value=='FAILED'  # zero counts do not prove no writes


def test_evidence_does_not_leak_into_next_source(capsys):
    def execute(config):
        if config.id=='a-source': diagnostics.mark('apply')
        raise RuntimeError('PRIVATE')
    run_sources([source('a-source'),source('b-source')],execute)
    values=[json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [v['write_outcome'] for v in values]==['MAY_HAVE_WRITTEN','NOT_STARTED']
    assert values[1]['stage']=='dispatch'


@pytest.mark.parametrize('url', ['https://example.test/api/SECRET/object/', 'https://example.test/api/dcim/devices/SECRET/', 'https://example.test/api2/json/nodes/SECRET'])
def test_unrecognized_http_path_not_echoed(url):
    value=diagnostics.record(error(503,url),diagnostics.ExecutionEvidence(),uuid4())
    assert value['http']=={'status':503,'method':'GET'}
    assert 'SECRET' not in json.dumps(value)


def test_causal_http_without_printing_exception_chain():
    try:
        try: raise error(401)
        except RequestError as exc: raise RuntimeError('PRIVATE') from exc
    except RuntimeError as exc:
        value=diagnostics.record(exc,diagnostics.ExecutionEvidence(stage='netbox'),uuid4())
    assert value['http']['status']==401
    assert value['exception_class']=='RuntimeError' and 'PRIVATE' not in json.dumps(value)


def test_connection_error_has_no_invented_http_status():
    value=diagnostics.record(requests.ConnectionError('PRIVATE'),diagnostics.ExecutionEvidence(stage='provider'),uuid4())
    assert 'http' not in value and value['stage']=='provider'
