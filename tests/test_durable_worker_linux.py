"""Real Unix transport/process durability with fake providers and disposable PostgreSQL."""
import json
import multiprocessing
import os
from pathlib import Path
import socket
import time
import pytest
from netbox_sync.discovery_worker import serve
from tests.test_source_operations_postgres import operations, plan
from tests.test_migrations_postgres import migration_database

pytestmark = pytest.mark.skipif(not hasattr(os, 'fork') or getattr(os, 'geteuid', lambda: -1)()!=0,
                               reason='Requires disposable Linux root test container')

class FakeProviderSupervisor:
    def __init__(self, store, calls): self.operations, self.calls = store, calls
    def run(self, source, kind):
        with open(self.calls, 'a') as log: log.write(source+':'+kind+'\n')
        time.sleep(0.8)
        if kind == 'plan': return plan(source)
        return dict(source_instance=source, source_type='proxmox', site_slug='test', cluster_name='Test', items=[])

def request(path, payload, disconnect=False):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(5);client.connect(str(path));client.sendall(json.dumps(payload).encode());client.shutdown(socket.SHUT_WR)
        if disconnect: return
        raw=b''
        while part:=client.recv(65536): raw+=part
        return json.loads(raw)

def test_disconnect_and_duplicate_requests_keep_one_provider_execution(operations, tmp_path):
    store, source = operations
    path=tmp_path/'worker.sock';calls=tmp_path/'calls'
    process=multiprocessing.get_context('fork').Process(target=serve,args=(str(path),FakeProviderSupervisor(store,str(calls)),0))
    process.start()
    try:
        deadline=time.monotonic()+5
        while not path.exists() and time.monotonic()<deadline: time.sleep(0.02)
        assert path.exists()
        request(path,dict(source_instance=source,operation='start_plan'),disconnect=True)
        deadline=time.monotonic()+5
        while not store.latest(source) and time.monotonic()<deadline: time.sleep(0.02)
        first=store.latest(source)[0]
        second=request(path,dict(source_instance=source,operation='start_plan'))
        assert second['ok'] and second['result']['operation']['operation_id']==str(first['operation_id'])
        request(path,dict(source_instance='second-source',operation='start_plan'))
        request(path,dict(source_instance=source,operation='start_discovery'))
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            rows=store.latest(source)+store.latest('second-source')
            if len(rows)==3 and all(row['status'] in ('READY','SUCCEEDED') for row in rows): break
            time.sleep(0.05)
        assert len(rows)==3 and all(row['status'] in ('READY','SUCCEEDED') for row in rows)
        assert calls.read_text().splitlines().count(source+':plan')==1
        reopened=request(path,dict(source_instance=source,operation='operations'))
        assert {row['status'] for row in reopened['result']['operations']}=={'READY','SUCCEEDED'}
        assert store.current_plan(source,plan(source)['digest'],first['operation_id'])==str(first['operation_id'])
    finally:
        process.terminate();process.join(5)
