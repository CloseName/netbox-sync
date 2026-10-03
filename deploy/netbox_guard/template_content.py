from netbox.plugins import PluginTemplateExtension
from .display import display_sections


class SyncDetails(PluginTemplateExtension):
    models = ['dcim.device', 'dcim.interface', 'virtualization.virtualmachine',
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


template_extensions = [SyncDetails, EsxiNetworkDetails]
