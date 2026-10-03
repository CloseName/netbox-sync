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


template_extensions = [SyncDetails]
