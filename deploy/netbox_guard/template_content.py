from netbox.plugins import PluginTemplateExtension
from .display import display_sections


class SyncDetails(PluginTemplateExtension):
    models = ['dcim.interface', 'virtualization.virtualmachine',
              'virtualization.vminterface']

    def right_page(self):
        obj = self.context.get('object')
        sections = display_sections(getattr(obj, 'custom_field_data', {}))
        if not sections:
            return ''
        return self.render('netbox_guard/sync_details.html', extra_context={
            'sync_sections': sections,
        })


class EsxiNetworkDetails(PluginTemplateExtension):
    models = ['dcim.device']

    def full_width_page(self):
        from .network_display import network_panel
        obj = self.context.get('object')
        panel = network_panel((getattr(obj, 'custom_field_data', {}) or {}).get('esxi_host_network'))
        if panel is None:
            return ''
        return self.render('netbox_guard/esxi_network.html', extra_context={'network_panel': panel})


class PfsenseNetworkDetails(PluginTemplateExtension):
    models = ['virtualization.virtualmachine']

    def full_width_page(self):
        from .pfsense_network import panel
        obj = self.context.get('object')
        value = panel((getattr(obj, 'custom_field_data', {}) or {}).get('pfsense_network'))
        if value is None:
            return ''
        return self.render('netbox_guard/pfsense_network.html', extra_context={'network_panel': value})


class PfsenseInventoryDetails(PluginTemplateExtension):
    models = ['virtualization.virtualmachine']

    def full_width_page(self):
        from .pfsense_inventory import panel
        obj = self.context.get('object')
        value = panel((getattr(obj, 'custom_field_data', {}) or {}).get('pfsense_inventory'))
        if value is None:
            return ''
        return self.render('netbox_guard/pfsense_inventory.html', extra_context={'inventory': value})


class NetworkLinks(PluginTemplateExtension):
    models = ['dcim.device', 'virtualization.cluster', 'virtualization.virtualmachine', 'virtualization.vminterface']

    def right_page(self):
        from .infrastructure import context, read_networks, same_network, visible
        from virtualization.models import VMInterface
        obj = self.context['object']
        kind={'device':'device','cluster':'cluster','virtualmachine':'vm','vminterface':'interface'}[obj._meta.model_name]
        request=self.context['request']
        _, guests=context(request.user,kind,obj.pk)
        networks=read_networks(request.user,guests)
        if kind in ('vm','interface'):
            current=visible(VMInterface,request.user).filter(virtual_machine_id=obj.pk) if kind=='vm' else visible(VMInterface,request.user).filter(pk=obj.pk)
            current=current.select_related('virtual_machine')
            anchors={n.pk:n for n in visible(VMInterface,request.user).filter(pk__in=[n['interface_id'] for n in networks]).select_related('virtual_machine')}
            networks=[n for n in networks if any(i.pk==n['interface_id'] or (n['interface_id'] in anchors and same_network(i,anchors[n['interface_id']])) for i in current)]
        return self.render('netbox_guard/network_link.html', extra_context={
            'network_kind':kind,'linked_networks':networks,
            'host_guests':guests if kind=='device' else None,
            'host_facts':(obj.custom_field_data or {}) if kind=='device' else {}})


template_extensions = [NetworkLinks, EsxiNetworkDetails, PfsenseNetworkDetails, PfsenseInventoryDetails]
