"""Native VM tab backed by the same permission-scoped pfSense snapshot as the overview."""
from django.shortcuts import get_object_or_404
from .pfsense_locale import lazy_label
from netbox.views import generic
from utilities.views import ViewTab, register_model_view
from virtualization.models import VirtualMachine

from .models import FirewallAppliance
from .pfsense_catalog import appliances
from .pfsense_catalog_views import appliance_context


@register_model_view(VirtualMachine, 'firewall')
class FirewallView(generic.ObjectView):
    queryset = VirtualMachine.objects.all()
    template_name = 'netbox_guard/vm_firewall.html'
    tab = ViewTab(label=lazy_label('Firewall'), weight=510, permission='virtualization.view_virtualmachine',
                  visible=lambda vm: FirewallAppliance.objects.filter(vm=vm).exists())

    def get_extra_context(self, request, instance):
        firewall = get_object_or_404(appliances(request.user), vm=instance)
        return appliance_context(request, firewall)
