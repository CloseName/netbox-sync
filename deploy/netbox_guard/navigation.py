"""Provider inventory entry point; visibility matches the registry view permission."""
from netbox.plugins import PluginMenu, PluginMenuItem


menu = PluginMenu(
    label='NetBox Sync',
    icon_class='mdi mdi-sync',
    groups=(
        ('Selectel', (
            PluginMenuItem(
                link='plugins:netbox_guard:provider_resources',
                link_text='Ресурсы провайдеров',
                permissions=['netbox_guard.view_resourceregistry'],
            ),
        )),
    ),
)
