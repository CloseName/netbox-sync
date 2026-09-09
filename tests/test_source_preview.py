"""Host-only summaries; no real hypervisors or credentials."""
import json
from types import SimpleNamespace as N
import pytest
from netbox_sync.source_preview import proxmox,esxi,MAX_HOSTS
from netbox_sync.application.onboarding import PendingCredentials


def test_proxmox_hosts_are_individual_without_invented_hardware():
    calls=[]
    def get(_host,_port,path,_context,_headers):
        calls.append(path)
        data={'/api2/json/cluster/status':[{'type':'cluster','name':'actual-cluster'}],
            '/api2/json/nodes':[{'node':'a'},{'node':'b'}],
            '/api2/json/nodes/a/status':{'cpuinfo':{'vendor':'Intel','model':'A'},'memory':{'total':32},'pveversion':'pve-manager/8.4'},
            '/api2/json/nodes/b/status':{'cpuinfo':{'vendor':'AMD','model':'B'},'memory':{'total':64}}}[path]
        return json.dumps({'data':data}).encode()
    result=proxmox(PendingCredentials('proxmox','pve.test',True,'user@realm','token',''), 'pve.test',None,get)
    assert result['cluster']=='actual-cluster'
    assert [(h['id'],h['cpu']) for h in result['hosts']]==[('a','A'),('b','B')]
    assert all(h['model'] is None and h['manufacturer'] is None for h in result['hosts'])
    assert len(calls)==4 and not any('/qemu' in c or '/lxc' in c for c in calls)


def test_proxmox_bound_before_node_reads():
    def get(_h,_p,path,*_):return json.dumps({'data':[] if path.endswith('/status') else [{'node':str(i)} for i in range(MAX_HOSTS+1)]}).encode()
    with pytest.raises(ValueError):proxmox(PendingCredentials('proxmox','pve.test',True,'u','t',''),'pve.test',None,get)


@pytest.mark.parametrize('manufacturer,model',[('Dell Inc.','PowerEdge R650'),('Supermicro','Super Server'),(None,None),(None,'R650')])
def test_esxi_host_summary_never_reads_vm_or_full_hardware(monkeypatch,manufacturer,model):
    import pyVmomi
    class Host:
        _moId='host-1';name='esxi.test'
        @property
        def vm(self):raise AssertionError('VM inventory must not be read')
        @property
        def hardware(self):raise AssertionError('Full hardware must not be read')
    class Folder:
        _moId='root'
        childEntity=[Host()]
    class Datacenter:pass
    class ComputeResource:pass
    monkeypatch.setattr(pyVmomi,'vim',N(HostSystem=Host,Folder=Folder,Datacenter=Datacenter,ComputeResource=ComputeResource))
    Host.summary=N(hardware=N(vendor=manufacturer,model=model,uuid='12345678-1234-4321-8765-123456789abc',memorySize=64),config=N(product=N(version='8.0')))
    result=esxi(N(about=N(apiType='HostAgent'),rootFolder=Folder()))
    assert result['cluster'] is None and len(result['hosts'])==1
    assert result['hosts'][0]['model']==model and result['hosts'][0]['manufacturer']==manufacturer
    assert result['hosts'][0]['id']=='12345678-1234-4321-8765-123456789abc'


def test_vcenter_is_not_silently_walked():
    with pytest.raises(ValueError):esxi(N(about=N(apiType='VirtualCenter')))
