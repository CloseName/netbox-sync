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


class ProxmoxNetworkDetails(PluginTemplateExtension):
    models = ['dcim.device']

    def full_width_page(self):
        from .network_display import proxmox_panel
        obj = self.context['object']
        panel = proxmox_panel((obj.custom_field_data or {}).get('proxmox_host_network'))
        if panel is None:
            return ''
        return self.render('netbox_guard/esxi_network.html', extra_context={
            'network_panel': panel, 'network_title': 'Сеть хоста Proxmox'})


class PfsenseNetworkDetails(PluginTemplateExtension):
    models = ['virtualization.virtualmachine']

    def full_width_page(self):
        from .pfsense_network import panel
        obj = self.context.get('object')
        value = panel((getattr(obj, 'custom_field_data', {}) or {}).get('pfsense_network'))
        if value is None:
            return ''
        return self.render('netbox_guard/pfsense_network.html', extra_context={'network_panel': value})


class ProviderNetworks(PluginTemplateExtension):
    models = ['dcim.device', 'ipam.ipaddress', 'ipam.prefix', 'ipam.vlan']

    def full_width_page(self):
        from .provider_network_display import document
        obj = self.context['object']
        value = document(self.context['request'].user, obj._meta.model_name, obj.pk)
        if not value['links']:
            return ''
        return self.render('netbox_guard/provider_networks.html', extra_context={'provider_networks': value})


class RoutingNativePanel(PluginTemplateExtension):
    models = ['ipam.vrf', 'ipam.prefix', 'ipam.ipaddress']

    def full_width_page(self):
        from .routing_links import panel
        from .routing_tabs import configure
        obj = self.context['object']
        if obj._meta.label_lower == 'ipam.prefix':
            from .routing_destinations import panel as destinations
            routes = destinations(self.context['request'].user, obj)
            if routes:
                return self.render('netbox_guard/routing_destination.html', extra_context={'routes': routes})
        value = panel(self.context['request'].user, self.context['object'], self.context['request'].GET.get('q', '')[:256])
        if value:
            value['is_router'] = self.context['object']._meta.model_name == 'vrf'
            configure(value, self.context['request'].GET)
        return self.render('netbox_guard/routing_native.html', extra_context={'routing': value}) if value else ''


template_extensions = [RoutingNativePanel, EsxiNetworkDetails, ProxmoxNetworkDetails, ProviderNetworks]
