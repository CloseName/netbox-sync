"""Disposable real NetBox checks for prerequisites, panels and reservations."""
import runpy
from pathlib import Path
# The production Dockerfile copies this shared parser into the plugin. A source
# mount used by the disposable model test needs the equivalent module mapping.
import importlib.util
import sys
spec=importlib.util.spec_from_file_location('netbox_guard.pfsense_preview',Path(__file__).parents[1]/'netbox_sync/pfsense_preview.py')
parser=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=parser
spec.loader.exec_module(parser)
runpy.run_path(str(Path(__file__).with_name('netbox_model_scope_scenario.py')))
from django.conf import settings
settings.ALLOWED_HOSTS=['testserver']
from django.contrib.auth import get_user_model
from django.test import RequestFactory, Client
from django.utils import timezone
from extras.models import CustomField
from ipam.models import VRF, Prefix, IPAddress
from dcim.models import MACAddress
from virtualization.models import VirtualMachine, VMInterface, Cluster, ClusterType
from netbox_guard.models import NetworkBinding, AddressReservation
from netbox_guard.managed_fields import configure_managed_fields
from netbox_guard.template_content import SyncDetails
from netbox_guard.network_views import availability, reserve, subnet
from uuid import uuid4

assert 'dcim.device' not in SyncDetails.models
for name in ('pfsense_inventory','pfsense_network'):
    field=CustomField.objects.get(name=name)
    assert field.type=='json' and field.ui_visible=='hidden' and field.ui_editable=='no'
    field.ui_visible='always';field.save()
configure_managed_fields()
assert not CustomField.objects.filter(name__startswith='pfsense_',ui_visible='always').exists()
suffix=uuid4().hex[:12]
user=get_user_model().objects.create_user(username='requirements-admin-'+suffix,is_superuser=True)
vrf=VRF.objects.create(name='requirements-'+suffix,enforce_unique=True)
prefix=Prefix.objects.create(prefix='10.24.0.0/24',vrf=vrf)
cluster=Cluster.objects.create(name='requirements-pve-'+suffix,type=ClusterType.objects.create(name='requirements-pve-'+suffix,slug='requirements-pve-'+suffix))
vm=VirtualMachine.objects.create(name='requirements-pfSense',cluster=cluster)
interface=VMInterface.objects.create(virtual_machine=vm,name='LAN')
mac=MACAddress.objects.create(mac_address='02:00:00:00:00:01',assigned_object=interface)
interface.primary_mac_address=mac;interface.save()
stamp=timezone.now().isoformat()
vm.custom_field_data={'pfsense_network':{'interfaces':[{
    'configuration':{'id':'lan','name':'LAN','device':'vtnet1'},
    'runtime':{'mac':str(mac.mac_address),'addresses':[{'address':'10.24.0.1/24'}]},'match':{'id':interface.pk}}]},
    'pfsense_inventory':{'collected_at':stamp,'ipam':{'configuration':'ok','arp':'ok','leases':'ok','interval_seconds':3600,'entries':[
        {'kind':'dhcp','interface':'lan','start':'10.24.0.100','end':'10.24.0.200','mac':''}]}}}
vm.save()
binding=NetworkBinding.objects.create(vm=vm,prefix=prefix,interface_key='lan',interface_id=interface.pk)
rows,_,fresh=availability(binding,user)
assert fresh and any(row['start']=='10.24.0.2' and row['state']=='candidate' for row in rows)
factory=RequestFactory()
def request(address,nonce=None):
    req=factory.post('/reserve/',{'address':address,'nonce':str(nonce or uuid4())});req.user=user
    return req
nonce=uuid4()
assert reserve(request('10.24.0.2',nonce),binding.pk).status_code==302
assert reserve(request('10.24.0.2',nonce),binding.pk).status_code==302
assert IPAddress.objects.filter(vrf=vrf,address__net_host='10.24.0.2').count()==1
assert IPAddress.objects.get(vrf=vrf,address__net_host='10.24.0.2').status=='reserved'
assert reserve(request('10.24.0.2'),binding.pk).status_code==409
assert reserve(request('10.24.0.150'),binding.pk).status_code==409
assert reserve(request('10.24.0.1'),binding.pk).status_code==409
assert reserve(request('10.25.0.2'),binding.pk).status_code==409
get=factory.get('/subnet/');get.user=user
assert subnet(get,binding.pk).status_code==200
from django.urls import reverse
client=Client(enforce_csrf_checks=True);client.force_login(user)
assert client.post(reverse('plugins:netbox_guard:reserve',kwargs={'pk':binding.pk}),{'address':'10.24.0.3','nonce':str(uuid4())}).status_code==403
print('PASS: automatic fields; hidden Device panel; native reservation; idempotency; DHCP/gateway/out-of-scope refusal; native page; CSRF')

from concurrent.futures import ThreadPoolExecutor
from django.db import close_old_connections
from django.core.exceptions import PermissionDenied
viewer=get_user_model().objects.create_user(username='requirements-viewer-'+suffix)
req=request('10.24.0.3');req.user=viewer
try: reserve(req,binding.pk)
except Exception as exc:
    from django.http import Http404
    assert isinstance(exc,(PermissionDenied,Http404))
else: raise AssertionError('Unprivileged reservation accepted')
assert not IPAddress.objects.filter(vrf=vrf,address__net_host='10.24.0.3').exists()
def concurrent_reservation(_):
    close_old_connections()
    try: return reserve(request('10.24.0.4'),binding.pk).status_code
    finally: close_old_connections()
with ThreadPoolExecutor(max_workers=2) as pool:
    assert sorted(pool.map(concurrent_reservation,range(2)))==[302,409]
assert IPAddress.objects.filter(vrf=vrf,address__net_host='10.24.0.4').count()==1
vm.custom_field_data['pfsense_inventory']['collected_at']='2000-01-01T00:00:00+00:00';vm.save()
assert reserve(request('10.24.0.5'),binding.pk).status_code==409
print('PASS: no write for unprivileged user; concurrent allocation produces one address; stale snapshot refuses reservation')
from django.core.management import call_command
call_command('makemigrations','netbox_guard',dry_run=True,check=True,verbosity=1)

assert 'netbox_guard.middleware.IPAMAllocationLock' in settings.MIDDLEWARE
vm.custom_field_data['pfsense_inventory']['collected_at']=timezone.now().isoformat();vm.save()
def native_creation():
    close_old_connections()
    try:
        native=Client();native.force_login(user)
        response=native.post('/ipam/ip-addresses/add/',{'address':'10.24.0.6/32','vrf':vrf.pk,'status':'active'})
        return response.status_code
    finally: close_old_connections()
def guarded_creation():
    close_old_connections()
    try: return reserve(request('10.24.0.6'),binding.pk).status_code
    finally: close_old_connections()
with ThreadPoolExecutor(max_workers=2) as pool:
    first=pool.submit(native_creation);second=pool.submit(guarded_creation)
    codes=(first.result(),second.result())
assert codes in ((302,409),(200,302)),codes
assert IPAddress.objects.filter(vrf=vrf,address__net_host='10.24.0.6').count()==1
call_command('configure_sync_catalog_permissions',user=viewer.username,verbosity=0)
call_command('configure_sync_catalog_permissions',user=viewer.username,verbosity=0)
from users.models import ObjectPermission
permission=ObjectPermission.objects.get(name='NetBox Sync catalog preparation / '+viewer.username)
assert set(permission.actions)=={'view','add'} and permission.object_types.count()==5
from dcim.models import Manufacturer,DeviceType
hardware=DeviceType(manufacturer=Manufacturer.objects.create(name='Unknown-'+suffix,slug='unknown-'+suffix),model='Hardware not identified',slug='unknown-hardware',u_height=0,exclude_from_utilization=True,is_full_depth=False)
hardware.full_clean();hardware.save()
print('PASS: native UI and Guard allocation race; narrow idempotent catalog grant; unknown hardware native validation')

from rest_framework.test import APIRequestFactory, force_authenticate
from ipam.api.views import IPAddressViewSet
def api_creation():
    close_old_connections()
    try:
        req=APIRequestFactory().post('/api/ipam/ip-addresses/',{'address':'10.24.0.7/32','vrf':vrf.pk,'status':'active'},format='json')
        force_authenticate(req,user=user)
        return IPAddressViewSet.as_view({'post':'create'})(req).status_code
    finally: close_old_connections()
def guard_api_race():
    close_old_connections()
    try: return reserve(request('10.24.0.7'),binding.pk).status_code
    finally: close_old_connections()
with ThreadPoolExecutor(max_workers=2) as pool:
    first=pool.submit(api_creation);second=pool.submit(guard_api_race)
    codes=(first.result(),second.result())
assert codes in ((201,409),(400,302)),codes
assert IPAddress.objects.filter(vrf=vrf,address__net_host='10.24.0.7').count()==1
before=vm.custom_field_data.copy()
configure_managed_fields();vm.refresh_from_db();assert vm.custom_field_data==before
print('PASS: native REST API allocation race; field reconciliation preserves stored JSON')

limited=get_user_model().objects.create_user(username='requirements-limited-'+suffix)
from django.contrib.contenttypes.models import ContentType
read_permission=ObjectPermission.objects.create(name='requirements-view-'+suffix,actions=['view'])
read_permission.object_types.set(ContentType.objects.get_for_models(VirtualMachine,Prefix,IPAddress).values());read_permission.users.add(limited)
add_permission=ObjectPermission.objects.create(name='requirements-add-'+suffix,actions=['add'],constraints={'vrf_id':vrf.pk+1000000})
add_permission.object_types.add(ContentType.objects.get_for_model(IPAddress));add_permission.users.add(limited)
limited=get_user_model().objects.get(pk=limited.pk)
assert limited.has_perm('ipam.add_ipaddress')
req=request('10.24.0.8');req.user=limited
try: reserve(req,binding.pk)
except PermissionDenied: pass
else: raise AssertionError('Object-constrained add permission bypassed')
assert not IPAddress.objects.filter(vrf=vrf,address__net_host='10.24.0.8').exists()
print('PASS: constrained add permission rolls back address and receipt')

# Common read model and prefix-free IP search, against actual NetBox models.
from dcim.models import Device, DeviceType, Manufacturer, DeviceRole, Site
from netbox_guard.infrastructure import read_networks, document
from netbox_guard.network_views import networks
from netbox_guard.template_content import template_extensions, NetworkLinks
from virtualization.models import VirtualDisk
site=Site.objects.create(name='backlog-'+suffix,slug='backlog-'+suffix)
maker=Manufacturer.objects.create(name='backlog-'+suffix,slug='backlog-'+suffix)
dtype=DeviceType.objects.create(manufacturer=maker,model='backlog-'+suffix,slug='backlog-'+suffix)
role=DeviceRole.objects.create(name='backlog-'+suffix,slug='backlog-'+suffix)
host=Device.objects.create(name='backlog-'+suffix,site=site,device_type=dtype,role=role,cluster=cluster)
vm.device=host
vm.custom_field_data['pfsense_inventory']['collected_at']=timezone.now().isoformat()
vm.save()
interface.custom_field_data={'source_bridge':'vmbr2','source_vlan_id':265,'sync_identities':[{'instance':'model-test'}]}
interface.save()
binding.delete()
guests=VirtualMachine.objects.filter(pk=vm.pk)
nets=read_networks(user,guests)
assert len(nets)==1 and nets[0]['cidr']=='10.24.0.0/24'
assert any(r['state']=='candidate' for r in nets[0]['rows'])
graph=document(user,'cluster',cluster.pk)
assert any(e['kind']=='hosted_on' and e['target']==f'device:{host.pk}' for e in graph['edges'])
assert any(e['kind']=='connected_to' for e in graph['edges'])
req=factory.get('/networks/',{'ip':'10.24.0.100'});req.user=user
page=networks(req,'cluster',cluster.pk)
assert page.status_code==200 and 'DHCP-пул'.encode() in page.content
req=factory.get('/networks/',{'ip':'10.25.0.2'});req.user=user
assert 'не относится к известным сетям'.encode() in networks(req,'cluster',cluster.pk).content
assert SyncDetails not in template_extensions
assert 'virtualization.virtualmachine' in NetworkLinks.models
assert read_networks(limited,guests)==[]  # No permission to view the matched NIC.
assert CustomField.objects.get(name='sync_disk_identity').type=='json'
VirtualDisk.objects.create(virtual_machine=vm,name='disk-test',size=1024,custom_field_data={'sync_disk_identity':{'external_id':'test'}})
vm.refresh_from_db();assert vm.disk==1024
print('PASS: prefix-free subnet search; graph host/NIC edges; hidden source panel; object permissions; native VirtualDisk aggregate')

from netbox_guard.api.infrastructure import Infrastructure, FirewallInventory
req=APIRequestFactory().get('/infrastructure/');force_authenticate(req,user=user)
response=Infrastructure.as_view()(req,kind='cluster',pk=cluster.pk)
assert response.status_code==200 and response.data['schema']=='netbox-sync.infrastructure.v1'
assert any(node['kind']=='site' for node in response.data['nodes'])
assert len({node['id'] for node in response.data['nodes']})==len(response.data['nodes'])
req=APIRequestFactory().get('/infrastructure/');force_authenticate(req,user=limited)
assert Infrastructure.as_view()(req,kind='cluster',pk=cluster.pk).status_code==404
import json
vm.custom_field_data['pfsense_inventory'].update(schema='netbox-sync.pfsense.inventory.snapshot.v1',vm_id=vm.pk,
    version='2.7.2',components=json.loads((Path(__file__).parent/'fixtures/pfsense_empty_components.json').read_text()),
    packages={'collection':'ok','items':[]},runtime={k:{'collection':'ok','text':''} for k in ('routes4','routes6','pf_filter','pf_nat')})
vm.save()
req=APIRequestFactory().get('/firewall/');force_authenticate(req,user=user)
response=FirewallInventory.as_view()(req,pk=vm.pk)
assert response.status_code==200 and 'pf_filter' not in response.data['runtime']
print('PASS: infrastructure API permissions, unique node IDs, firewall runtime evidence')
client=Client();client.force_login(user)
assert client.get(vm.get_absolute_url()).status_code==200
assert client.get(host.get_absolute_url()).status_code==200
print('PASS: native VM and Device pages render with the common network panel')
