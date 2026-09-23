"""Real loopback HTTP through NetBox WSGI/DRF/token auth; isolated DB only."""
import runpy,threading,secrets,json
from pathlib import Path
from uuid import uuid4
from datetime import timedelta
runpy.run_path(str(Path(__file__).with_name('netbox_model_scope_scenario.py')))
from django.conf import settings
from django.db import connection,connections
assert connection.settings_dict['NAME']=='netbox_sync_guard_test'
settings.ALLOWED_HOSTS=['127.0.0.1']
settings.API_TOKEN_PEPPERS={1:secrets.token_urlsafe(64)}
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.apps import apps
from users.models import ObjectPermission,Token
from virtualization.models import ClusterType,Cluster,VirtualMachine
from dcim.models import Site,Manufacturer,DeviceType,DeviceRole,Device
from netbox_guard.models import CreationReceipt,CreationClaim,RetirementIntent,RetirementReceipt
from netbox_guard.dependencies import MODELS
from django.core.wsgi import get_wsgi_application
from wsgiref.simple_server import make_server,WSGIRequestHandler
import requests
import ssl,tempfile,ipaddress,importlib.util
from datetime import datetime,timezone as datetime_timezone
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
certdir=tempfile.TemporaryDirectory(prefix='guard-http-')
key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'isolated-loopback')])
now=datetime.now(datetime_timezone.utc)
cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
    .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
    .not_valid_after(now+timedelta(hours=1))
    .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False)
    .add_extension(x509.BasicConstraints(ca=True,path_length=0),True).sign(key,hashes.SHA256()))
certfile=Path(certdir.name)/'cert.pem';keyfile=Path(certdir.name)/'key.pem'
certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
keyfile.touch(mode=0o600);keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
session=requests.Session();session.trust_env=False;session.verify=str(certfile)
spec=importlib.util.spec_from_file_location('guard_transport',Path('/app/netbox_sync/retirement_transport.py'))
transport=importlib.util.module_from_spec(spec);spec.loader.exec_module(transport)
class Quiet(WSGIRequestHandler):
    def log_message(self,*args): pass
server=make_server('127.0.0.1',0,get_wsgi_application(),handler_class=Quiet)
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(certfile,keyfile)
server.socket=context.wrap_socket(server.socket,server_side=True)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
url='https://127.0.0.1:'+str(server.server_port)+'/api/plugins/netbox-sync-guard/'
tag='guard-http-'+uuid4().hex
source='esxi-'+uuid4().hex
User=get_user_model();user=User.objects.create(username=tag,is_active=True)
kind=ClusterType.objects.create(name=tag,slug=tag)
site=Site.objects.create(name=tag,slug=tag)
manufacturer=Manufacturer.objects.create(name=tag,slug=tag)
device_type=DeviceType.objects.create(manufacturer=manufacturer,model=tag,slug=tag)
role=DeviceRole.objects.create(name=tag,slug=tag)
cap=ObjectPermission.objects.create(name=tag,actions=['create','retire'],constraints={'source_instance':source})
cap.object_types.set([ContentType.objects.get_for_model(CreationReceipt),ContentType.objects.get_for_model(RetirementIntent)])
cap.users.add(user)
add=ObjectPermission.objects.create(name=tag+'-add',actions=['add'])
add.object_types.set([ContentType.objects.get_for_model(apps.get_model(label)) for label in MODELS.values()]);add.users.add(user)
tokens=[];headers=[];clusters=[]
for enabled in (True,False):
    token=Token(user=user,write_enabled=enabled,expires=timezone.now()+timedelta(minutes=5))
    token.full_clean();token.save();tokens.append(token)
    headers.append({'Authorization':token.get_auth_header_prefix()+token.token})
def post(path,body,auth=headers[0]):
    response=session.post(url+path,json=body,headers=auth,timeout=15)
    assert all(token.token not in response.text for token in tokens)
    return response
try:
    assert session.get(url+'capabilities/',timeout=10).status_code in (401,403)
    capability=session.get(url+'capabilities/',headers=headers[1],timeout=10).json()
    assert capability['protocol']==1
    for header in headers: header['X-Netbox-Sync-Guard-Instance']=capability['guard_instance']
    client=transport.GuardClient(session,url.split('/api/')[0],headers[0]['Authorization'],capability['guard_instance'])
    assert client.capabilities()==capability
    body={'nonce':str(uuid4()),'source_instance':source,'resource':'cluster','cluster_id':None,'data':{'name':tag,'type':kind.pk,'scope_type':'dcim.site','scope_id':site.pk}}
    assert post('objects/create/',body,headers[1]).status_code==403
    changed={**headers[0],'X-Netbox-Sync-Guard-Instance':str(uuid4())}
    assert post('objects/create/',body,changed).json()['code']=='GUARD_INSTANCE_CHANGED'
    assert not Cluster.objects.filter(name=tag).exists()
    result=post('objects/create/',body)
    assert result.status_code==201,(result.status_code,result.text)
    cluster=result.json()['id'];clusters.append(cluster)
    assert post('objects/create/',body).json()['id']==cluster
    assert client.create(body['nonce'],source,'cluster',None,body['data'])['id']==cluster
    wrong={**body,'nonce':str(uuid4()),'source_instance':'esxi-not-allowed','data':{'name':tag+'-foreign','type':kind.pk}}
    assert post('objects/create/',wrong).status_code==403
    assert not Cluster.objects.filter(name=tag+'-foreign').exists()
    device_body={'nonce':str(uuid4()),'source_instance':source,'resource':'device','cluster_id':cluster,
        'data':{'name':tag+'-host','site':site.pk,'role':role.pk,'device_type':device_type.pk,'cluster':cluster}}
    result=post('objects/create/',device_body);assert result.status_code==201,(result.status_code,result.text)
    host=result.json()['id']
    vm_body={'nonce':str(uuid4()),'source_instance':source,'resource':'vm','cluster_id':cluster,'data':{'name':'owned-http-vm','cluster':cluster,'device':host,'vcpus':4,'memory':8192,'disk':20}}
    result=post('objects/create/',vm_body);assert result.status_code==201,(result.status_code,result.text)
    vm=result.json()['id']
    def child(resource,data):
        value={'nonce':str(uuid4()),'source_instance':source,'resource':resource,'cluster_id':cluster,'data':data}
        response=post('objects/create/',value)
        assert response.status_code==201,(resource,response.status_code,response.text)
        return response.json()['id']
    physical=child('interface',{'device':host,'name':'vmk0','type':'virtual'})
    child('ip',{'address':'192.0.2.187/24','assigned_object_type':'dcim.interface','assigned_object_id':physical})
    nic=child('vminterface',{'virtual_machine':vm,'name':'eth0'})
    child('ip',{'address':'192.0.2.188/24','assigned_object_type':'virtualization.vminterface','assigned_object_id':nic})
    child('mac',{'mac_address':'02:00:00:00:42:11','assigned_object_type':'virtualization.vminterface','assigned_object_id':nic})
    child('disk',{'virtual_machine':vm,'name':'disk0','size':20480})
    assert not User.objects.get(pk=user.pk).has_perm('virtualization.delete_virtualmachine')
    # Every phase uses source-bound server permissions and read-only token refusal.
    for root in (['vm',vm],['device',host],['cluster',cluster]):
        proposal={'nonce':str(uuid4()),'source_instance':source,'cluster_id':cluster,'root':root}
        result=post('retirements/review/',proposal);assert result.status_code==200,result.text
        intent=result.json()
        assert client.review(proposal['nonce'],source,cluster,root)==intent
        execution={'nonce':intent['nonce'],'digest':intent['digest']}
        assert post('retirements/execute/',execution,headers[1]).status_code==403
        done=post('retirements/execute/',execution);assert done.status_code==200,done.text
        assert done.json()['status']=='SUCCEEDED'
        assert post('retirements/execute/',execution).json()==done.json()
        assert client.execute(intent['nonce'],intent['digest'])==done.json()
        assert client.receipt(intent['nonce'])==done.json()
        observed=session.get(url+'retirements/'+intent['nonce']+'/',headers=headers[1],timeout=10)
        assert observed.json()==done.json()
    assert not Cluster.objects.filter(pk=cluster).exists()
    assert not VirtualMachine.objects.filter(pk=vm).exists()
    assert ClusterType.objects.filter(pk=kind.pk).exists()
    # Revocation takes effect on a new authenticated request.
    tokens[0].enabled=False;tokens[0].save()
    assert post('objects/create/',{**body,'nonce':str(uuid4())}).status_code in (401,403)
    print('PASS real HTTP: v2 token authentication; read-only refusal; source constraints; create/retry; VM/cluster receipts; no generic delete privilege; revoked token refusal')
finally:
    server.shutdown();server.server_close();thread.join(3)
    VirtualMachine.objects.filter(cluster_id__in=clusters).delete()
    Device.objects.filter(cluster_id__in=clusters).delete()
    Cluster.objects.filter(pk__in=clusters).delete()
    RetirementReceipt.objects.filter(intent__source_instance=source).delete()
    RetirementIntent.objects.filter(source_instance=source).delete()
    CreationReceipt.objects.filter(source_instance=source).delete()
    CreationClaim.objects.filter(source_instance=source).delete()
    add.delete();cap.delete();kind.delete();user.delete()
    device_type.delete();manufacturer.delete();role.delete();site.delete()
    session.close();certdir.cleanup()
    connections.close_all()
