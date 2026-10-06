from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.http import Http404
from ..infrastructure import document, visible
from ..pfsense_inventory import validate
from virtualization.models import VirtualMachine
from django.shortcuts import get_object_or_404

class Infrastructure(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request, kind, pk):
        try: value=document(request.user,kind,pk)
        except ValueError: raise Http404
        return Response(value)

class FirewallInventory(APIView):
    permission_classes = [IsAuthenticated]
    def get(self,request,pk):
        vm=get_object_or_404(visible(VirtualMachine,request.user),pk=pk)
        raw=(vm.custom_field_data or {}).get('pfsense_inventory')
        if not isinstance(raw,dict): return Response({'schema':'netbox-sync.firewall.v1','state':'unavailable','components':{},'limitations':['NO_SNAPSHOT']})
        try: clean=validate({**raw,'schema':'netbox-sync.pfsense.inventory.v1'})
        except (ValueError,KeyError,TypeError): return Response({'schema':'netbox-sync.firewall.v1','state':'invalid','components':{},'limitations':['INVALID_SNAPSHOT']})
        return Response({'schema':'netbox-sync.firewall.v1','vm_id':vm.pk,'collected_at':clean['collected_at'],
            'components':clean['components'],'runtime':clean['runtime'],
            'limitations':['ANCHORS_NOT_COLLECTED','DYNAMIC_TABLE_CONTENTS_NOT_COLLECTED','EFFECTIVE_POLICY_NOT_EVALUATED']})
