"""Narrow authenticated transport; no generic delete/claim-adoption API."""
import json
import logging
from uuid import UUID, uuid4
from django.apps import apps
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from netbox.api.authentication import TokenWritePermission
from ..dependencies import MODELS, DependencyGuardBlocked, _digest
from ..models import RetirementIntent, RetirementReceipt, GuardIdentity, CreationReceipt
from ..service import create_owned, review, retire, _permission

SERIALIZERS = {
    'cluster': ('virtualization.api.serializers','ClusterSerializer'),
    'vm': ('virtualization.api.serializers','VirtualMachineSerializer'),
    'vminterface': ('virtualization.api.serializers','VMInterfaceSerializer'),
    'disk': ('virtualization.api.serializers','VirtualDiskSerializer'),
    'device': ('dcim.api.serializers','DeviceSerializer'),
    'interface': ('dcim.api.serializers','InterfaceSerializer'),
    'mac': ('dcim.api.serializers','MACAddressSerializer'),
    'ip': ('ipam.api.serializers','IPAddressSerializer'),
}


def _body(request, fields):
    if len(request.body)>32768:
        raise DependencyGuardBlocked('REQUEST_TOO_LARGE')
    try: value=json.loads(request.body)
    except (ValueError, UnicodeError): raise DependencyGuardBlocked('REQUEST_INVALID') from None
    if not isinstance(value,dict) or set(value)!=set(fields):
        raise DependencyGuardBlocked('REQUEST_INVALID')
    return value


def _public(intent, receipt=None):
    return {'nonce':str(intent.pk),'source_instance':intent.source_instance,
            'digest':intent.digest,'status':'SUCCEEDED' if receipt else 'REVIEWED',
            'manifest':intent.manifest,'deleted':receipt.deleted if receipt else []}


class GuardView(APIView):
    permission_classes=(IsAuthenticated,TokenWritePermission)
    namespace_required=True

    def initial(self,request,*args,**kwargs):
        super().initial(request,*args,**kwargs)
        if self.namespace_required:
            identity=str(GuardIdentity.objects.get(pk=1).identifier)
            if request.headers.get('X-Netbox-Sync-Guard-Instance')!=identity:
                raise DependencyGuardBlocked('GUARD_INSTANCE_CHANGED')

    def handle_exception(self, exc):
        if isinstance(exc, DependencyGuardBlocked):
            return Response({'code':str(exc)},status=403 if str(exc)=='PERMISSION_DENIED' else 409)
        # A serializer can fail AFTER the transaction committed. Do not label
        # arbitrary ValueError/TypeError as a definitive pre-write refusal.
        if isinstance(exc,RetirementIntent.DoesNotExist):
            return Response({'code':'REQUEST_NOT_FOUND'},status=404)
        from rest_framework.exceptions import APIException
        if isinstance(exc,APIException):
            # Keep status semantics without returning serializer/remote value text.
            response=super().handle_exception(exc)
            response.data={'code':'AUTHENTICATION_REQUIRED' if response.status_code==401 else 'REQUEST_REFUSED'}
            return response
        event=str(uuid4())
        logging.getLogger(__name__).error('guard_event=%s exception_class=%s',event,type(exc).__name__)
        return Response({'code':'GUARD_UNAVAILABLE','event_id':event},status=503)


class Capabilities(GuardView):
    namespace_required=False
    def get(self,request):
        return Response({'protocol':1,'guard_instance':str(GuardIdentity.objects.get(pk=1).identifier),'netbox_version':'4.7.0','atomic_dependency_guard':True,
                         'creation_receipts':True,'retirement_receipts':True,
                         'source_coordinator_required':True})


class CreateOwned(GuardView):
    def post(self,request):
        from importlib import import_module
        body=_body(request,('nonce','source_instance','resource','cluster_id','data'))
        kind=body['resource']
        if not isinstance(kind,str) or kind not in SERIALIZERS or not isinstance(body['data'],dict):
            raise DependencyGuardBlocked('REQUEST_INVALID')
        if any(key in body['data'] for key in ('id','pk','tags')):
            raise DependencyGuardBlocked('REQUEST_INVALID')
        module,name=SERIALIZERS[kind]
        serializer_class=getattr(import_module(module),name)
        try: nonce=UUID(str(body['nonce']))
        except (ValueError,TypeError): raise DependencyGuardBlocked('REQUEST_INVALID') from None
        wire_digest=_digest(body)
        previous=CreationReceipt.objects.filter(nonce=nonce).first()
        if previous is not None:
            # Exact wire digest, actor, source, resource, generation and ownership
            # are checked by the transaction service. Never run CREATE uniqueness
            # validation against an object whose creation already committed.
            obj=create_owned(request.user,nonce,body['source_instance'],kind,{},
                             cluster=body['cluster_id'],request_digest=wire_digest)
            return Response(serializer_class(obj,context={'request':request}).data,status=201)
        serializer=serializer_class(data=body['data'],context={'request':request})
        if any(key not in serializer.fields or serializer.fields[key].read_only for key in body['data']):
            raise DependencyGuardBlocked('OBJECT_FIELDS_UNSUPPORTED')
        if not serializer.is_valid(): raise DependencyGuardBlocked('OBJECT_INVALID')
        # Runtime Sync CREATEs use fixed scalar/FK/custom-field payloads. Never
        # expand this into nested arbitrary model creation via a generic endpoint.
        values=dict(serializer.validated_data)
        for key in tuple(values):
            try: field=apps.get_model(MODELS[kind])._meta.get_field(key)
            except Exception: raise DependencyGuardBlocked('OBJECT_FIELDS_UNSUPPORTED') from None
            if field.many_to_many:
                if values.pop(key): raise DependencyGuardBlocked('OBJECT_FIELDS_UNSUPPORTED')
        obj=create_owned(request.user,body['nonce'],body['source_instance'],kind,values,cluster=body['cluster_id'],request_digest=wire_digest)
        return Response(serializer_class(obj,context={'request':request}).data,status=201)


class Review(GuardView):
    def post(self,request):
        body=_body(request,('nonce','source_instance','cluster_id','root'))
        root=body['root']
        if not isinstance(root,list) or len(root)!=2:
            raise DependencyGuardBlocked('REQUEST_INVALID')
        intent=review(request.user,body['nonce'],body['source_instance'],body['cluster_id'],root=body['root'])
        receipt=RetirementReceipt.objects.filter(intent=intent).first()
        return Response(_public(intent,receipt))


class Retire(GuardView):
    def post(self,request):
        body=_body(request,('nonce','digest'))
        receipt=retire(request.user,body['nonce'],body['digest'])
        return Response(_public(receipt.intent,receipt))


class Receipt(GuardView):
    def get(self,request,nonce):
        intent=RetirementIntent.objects.get(pk=UUID(str(nonce)))
        actor=_permission(request.user,'retire_retirementintent',intent)
        if actor!=intent.actor: raise DependencyGuardBlocked('PERMISSION_DENIED')
        return Response(_public(intent,RetirementReceipt.objects.filter(intent=intent).first()))
