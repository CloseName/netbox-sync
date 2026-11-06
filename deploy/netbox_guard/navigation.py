"""Provider inventory entry point; visibility matches the registry view permission."""
from netbox.plugins import PluginMenu, PluginMenuItem


menu = PluginMenu(
    label='NetBox Sync',
    icon_class='mdi mdi-sync',
    groups=(
        ('pfSense', (
            PluginMenuItem(link='plugins:netbox_guard:pfsense_overview', link_text='pfSense',
                           permissions=['virtualization.view_virtualmachine']),
            PluginMenuItem(link='plugins:netbox_guard:pfsense_search', link_text='Поиск объектов pfSense',
                           permissions=['virtualization.view_virtualmachine']),
        )),
        ('Selectel', (
            PluginMenuItem(
                link='plugins:netbox_guard:provider_resources',
                link_text='Ресурсы провайдеров',
                permissions=['netbox_guard.view_resourceregistry'],
            ),
            PluginMenuItem(
                link='plugins:netbox_guard:routing_overview',
                link_text='Сети Selectel',
                permissions=['netbox_guard.view_resourceregistry'],
            ),
        )),
    ),
)
