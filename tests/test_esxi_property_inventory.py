"""Real local HTTPS/SOAP request counts, no hypervisor or apply."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
import ssl
import subprocess
import threading
import time
from xml.etree import ElementTree as ET
import pytest
from tests.probe_https_fixture import Handler as Base
from tests.fakes.esxi_properties import properties
from tests.fakes.esxi_property_reply import property_reply
from tests.test_esxi import esxi_config, FakeResolver
from netbox_sync.esxi_client import EsxiClient
from netbox_sync.esxi_discovery import discover_hosts, _walk_hosts, _convert_hosts


@contextmanager
def endpoint(tmp_path, monkeypatch, count=147, delay=0, incomplete=False):
    cert=tmp_path/'cert.pem';key=tmp_path/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
        '-keyout',str(key),'-out',str(cert),'-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],
        check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    monkeypatch.setenv('SSL_CERT_FILE',str(cert))
    rows=deepcopy(properties)
    refs=[]
    for i in range(count):
        ident='vm-'+str(1000+i);refs.append('<ManagedObjectReference type="VirtualMachine">'+ident+'</ManagedObjectReference>')
        for field in ('name','config','guest','runtime','summary'):
            value=properties[('vm-42',field)]
            if field=='config':
                value=value.replace('503c5ad7-0000-1111-2222-0123456789ab','503c5ad7-0000-1111-2222-'+format(i,'012x'))
                value=value.replace('<name>ESXI-VM</name>','<name>ESXI-VM</name><annotation>'+('Notes\n'*80)+'</annotation>')
            rows[(ident,field)]=value
    rows[('ha-host','vm')]='<val xsi:type="ArrayOfManagedObjectReference">'+''.join(refs)+'</val>'
    calls=[]
    class Handler(Base):
        def do_POST(self):
            body=self.rfile.read(int(self.headers.get('Content-Length','0')))
            method=next(iter(next(e for e in ET.fromstring(body) if e.tag.endswith('Body'))))
            name=method.tag.split('}')[-1];calls.append(name)
            if name=='RetrievePropertiesEx':
                time.sleep(delay)
                if incomplete:
                    return self.soap('<RetrievePropertiesExResponse xmlns="urn:vim25"><returnval/></RetrievePropertiesExResponse>')
            reply=property_reply(method,rows)
            if reply is not None: return self.soap(reply)
            self.rfile=BytesIO(body)
            return super().do_POST()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    config=replace(esxi_config(),address='127.0.0.1',settings={'api_port':server.server_port})
    try: yield config, calls
    finally: server.shutdown();server.server_close();thread.join(timeout=2)


def test_representative_inventory_request_count_and_exact_equivalence(tmp_path,monkeypatch):
    from netbox_sync import esxi_inventory
    phases=[]
    monkeypatch.setattr(esxi_inventory,'phase_progress',lambda name, elapsed=None, **stats: phases.append((name, elapsed, stats)))
    client=EsxiClient(resolver=FakeResolver())
    with endpoint(tmp_path,monkeypatch) as (config,calls):
        with client.session(config) as service:
            calls.clear()
            # The same mapper over uncached real pyVmomi properties reproduces
            # repeated remote reads in the previous implementation.
            baseline=_convert_hosts(list(_walk_hosts(service.RetrieveContent().rootFolder)),config)
            previous=len(calls);calls.clear()
            result=discover_hosts(service,config)
            current=len(calls)
            assert [asdict(h) for h in result]==[asdict(h) for h in baseline]
            assert len(result[0].virtual_machines)==147
            assert all(vm.description=='Notes\n'*80 for vm in result[0].virtual_machines)
            assert all(vm.interfaces[0].ip_addresses==['10.20.40.42/24'] for vm in result[0].virtual_machines)
            assert calls.count('RetrievePropertiesEx')==2
            assert current<=15 and previous>147*10
            assert next(stats for name,elapsed,stats in phases if name=='esxi_conversion' and elapsed is not None)['requests']==0
            print('SOAP requests for 147 VMs: previous=%d current=%d'%(previous,current))
            calls.clear();again=discover_hosts(service,config)
            assert [asdict(h) for h in again]==[asdict(h) for h in result]
            assert calls.count('RetrievePropertiesEx')==2 # no cross-run cache


def test_incomplete_batch_never_becomes_success(tmp_path,monkeypatch):
    with endpoint(tmp_path,monkeypatch,count=2,incomplete=True) as (config,calls):
        with EsxiClient(resolver=FakeResolver()).session(config) as service:
            with pytest.raises(RuntimeError,match='incomplete'): discover_hosts(service,config)
            assert calls.count('RetrievePropertiesEx')==1


def test_slow_request_times_out_without_retry(tmp_path,monkeypatch):
    import netbox_sync.esxi_client as client
    monkeypatch.setattr(client,'ESXI_IO_TIMEOUT',.2)
    with endpoint(tmp_path,monkeypatch,count=2,delay=1) as (config,calls):
        with EsxiClient(resolver=FakeResolver()).session(config) as service:
            start=time.monotonic()
            with pytest.raises(TimeoutError): discover_hosts(service,config)
            assert time.monotonic()-start<1
            assert calls.count('RetrievePropertiesEx')==1


def test_pagination_faults_and_missing_properties_fail_closed():
    from types import SimpleNamespace as N
    from pyVmomi import vim
    from netbox_sync.esxi_inventory import InventoryReads
    objects=[vim.VirtualMachine('vm-'+str(i)) for i in range(2)]
    paths=('name','config','guest','runtime','summary')
    def row(obj): return N(obj=obj, missingSet=[], propSet=[N(name=p,val=N()) for p in paths])
    reads=InventoryReads(N(_stub=N()))
    class Collector:
        calls=0
        def RetrievePropertiesEx(self,**_):self.calls+=1;return N(objects=[row(objects[0])],token='opaque')
        def ContinueRetrievePropertiesEx(self,token):self.calls+=1;assert token=='opaque';return N(objects=[row(objects[1])],token='')
    collector=Collector();reads.virtual_machines(collector,objects)
    assert collector.calls==2 and len(reads.values)==10
    class Fault(Collector):
        def ContinueRetrievePropertiesEx(self,token):raise TimeoutError('private remote text')
    with pytest.raises(TimeoutError):reads.virtual_machines(Fault(),objects)
    class Missing(Collector):
        def ContinueRetrievePropertiesEx(self,token):
            value=row(objects[1]);value.missingSet=[N(fault='private')];return N(objects=[value],token='')
    with pytest.raises(RuntimeError,match='incomplete'):reads.virtual_machines(Missing(),objects)


@pytest.mark.skipif(__import__('os').name!='posix' or __import__('os').environ.get('NETBOX_SYNC_TIMEOUT_TEST')!='1',reason='isolated root cross-UID runtime')
@pytest.mark.parametrize('hang',[False,True])
def test_actual_worker_plan_or_bounded_provider_hang(tmp_path,monkeypatch,hang):
    import os
    import tempfile
    from pathlib import Path
    from netbox_sync import discovery_worker as worker
    from netbox_sync.source_config import SecretReference, SourceCredentials
    from tests.fakes import FakeNetBox
    from tests.fakes.netbox_http import netbox_http
    from tests.test_first_sync import target
    monkeypatch.setattr(worker,'DISCOVERY_TIMEOUT',1.5 if hang else 20)
    for name in ('password','netbox-token'): (tmp_path/name).write_text('controlled-fixture')
    processes=[]
    def spawn(*args,**kwargs):
        process=subprocess.Popen(*args,**kwargs);processes.append(process);return process
    with endpoint(tmp_path,monkeypatch,count=1,delay=4 if hang else 0) as (config,calls):
        config=replace(config,credentials=SourceCredentials.for_password('fixture',SecretReference('file','password')))
        seed=FakeNetBox();target(seed,config)
        with tempfile.TemporaryDirectory(prefix='netbox-sync-esxi-ca-') as directory:
            directory=Path(directory);directory.chmod(0o755)
            ca=directory/'public.pem';ca.write_bytes((tmp_path/'cert.pem').read_bytes());ca.chmod(0o644)
            original=worker._safe_environment
            monkeypatch.setattr(worker,'_safe_environment',lambda:{**original(),'SSL_CERT_FILE':str(ca)})
            with netbox_http(seed) as (api,rows,writes):
                supervisor=worker.DiscoverySupervisor('reader','netbox_sync',tmp_path,tmp_path,api.base_url.rstrip('/').removesuffix('/api'),tmp_path/'netbox-token',10001,10001,popen=spawn)
                monkeypatch.setattr(supervisor,'_source',lambda _:config)
                started=time.monotonic()
                if hang:
                    with pytest.raises(worker.WorkerError) as caught:supervisor.run(config.source_instance,'plan')
                    error=caught.value
                    assert error.code=='DISCOVERY_TIMEOUT'
                    assert error.diagnostic['child_reaped'] and error.diagnostic['returncode']==-9
                    assert time.monotonic()-started<3
                    assert error.diagnostic['phases'][-1]=={'phase':'esxi_properties','state':'started'}
                else:
                    try: plan=supervisor.run(config.source_instance,'plan')
                    except worker.WorkerError as error: pytest.fail(json.dumps(error.diagnostic))
                    assert plan['digest'] and plan['items']
                    assert any(item['object_kind']=='virtualization.virtual_machines' and item['action']=='CREATE' for item in plan['items'])
                assert writes==[]
                with pytest.raises(ChildProcessError):os.waitpid(processes[0].pid,os.WNOHANG)
