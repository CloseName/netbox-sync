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
    models = ['dcim.device', 'virtualization.cluster']

    def right_page(self):
        obj = self.context['object']
        return self.render('netbox_guard/network_link.html', extra_context={
            'network_kind':'device' if obj._meta.model_name=='device' else 'cluster'})


template_extensions = [NetworkLinks, SyncDetails, EsxiNetworkDetails, PfsenseNetworkDetails, PfsenseInventoryDetails]
