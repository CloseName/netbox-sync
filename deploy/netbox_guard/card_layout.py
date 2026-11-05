"""Per-response NetBox 4.7 layout additions; no mutation of shared view layouts."""
from copy import copy
from django.utils.deprecation import MiddlewareMixin
from django.urls import reverse
from urllib.parse import urlencode
from netbox.ui.panels import Panel
from ipam.models import IPAddress
from .provider_card_display import panel as provider_panel
from .hardware_display import panel as hardware_panel


class AddressesPanel(Panel):
    template_name = 'netbox_guard/provider_card.html'

    def get_context(self, context):
        result = super().get_context(context)
        obj = context['object']
        value = provider_panel((obj.custom_field_data or {}).get('selectel_inventory'))
        rows = []
        if value:
            for address in value['addresses']:
                query = IPAddress.objects.restrict(context['request'].user, 'view').filter(address__net_host=address)
                matches = list(query[:2])
                url = matches[0].get_absolute_url() if len(matches) == 1 else reverse('ipam:ipaddress_list') + '?' + urlencode({'q': address})
                rows.append(dict(address=address, url=url, primary=bool(obj.primary_ip4 and str(obj.primary_ip4.address.ip) == address)))
        result['provider_addresses'] = rows
        return result

    def should_render(self, context):
        return bool(context['provider_addresses'])


class HardwarePanel(Panel):
    template_name = 'netbox_guard/hardware_card.html'

    def get_context(self, context):
        return {**super().get_context(context), 'hardware': hardware_panel(context['object'].custom_field_data)}

    def should_render(self, context):
        return bool(context['hardware'])


class InventoryLayout(MiddlewareMixin):
    def process_view(self, request, callback, callback_args, callback_kwargs):
        match = request.resolver_match
        if match and match.view_name == 'search':
            from .search_views import InventorySearchView
            return InventorySearchView.as_view()(request, *callback_args, **callback_kwargs)
        if not match or match.view_name not in ('dcim:device', 'virtualization:virtualmachine'):
            return None
        view_class = getattr(callback, 'view_class', None)
        original = getattr(view_class, 'layout', None)
        if original is None:
            return None
        # ObjectView uses django.shortcuts.render(), not TemplateResponse.
        # A request-local subclass preserves dispatch/permissions and the shared layout.
        layout = inventory_layout(original, match.view_name == 'dcim:device')
        adapted = type('InventoryView', (view_class,), {'layout': layout})
        return adapted.as_view(**getattr(callback, 'view_initkwargs', {}))(
            request, *callback_args, **callback_kwargs)

    def process_template_response(self, request, response):
        context = response.context_data
        match = request.resolver_match
        if context and match and match.view_name in ('dcim:device', 'virtualization:virtualmachine'):
            if context.get('layout') is not None:
                context['layout'] = inventory_layout(context['layout'], match.view_name == 'dcim:device')
        return response


def inventory_layout(original, device):
    layout = copy(original)
    layout.rows = [copy(row) for row in original.rows]
    for row in layout.rows:
        row.columns = [copy(column) for column in row.columns]
        for column in row.columns:
            panels = []
            for panel in column.panels:
                if isinstance(panel, (AddressesPanel, HardwarePanel)):
                    continue
                panels.append(panel)
                anchor = 'DeviceManagementPanel' if device else 'VirtualMachinePanel'
                if panel.__class__.__name__ == anchor:
                    panels.append(AddressesPanel())
                    if device:
                        panels.append(HardwarePanel())
            column.panels = panels
    return layout
