"""Optional NetBox-side guard; installing this package is a separate action."""
from netbox.plugins import PluginConfig

class NetBoxGuardConfig(PluginConfig):
    name = 'netbox_guard'
    verbose_name = 'NetBox Sync guarded lifecycle'
    description = 'Atomic source-owned lifecycle receipts'
    version = '0.1.0'
    min_version = '4.7.0'
    max_version = '4.7.0'
    base_url = 'netbox-sync-guard'

    def ready(self):
        super().ready()
        from . import signals  # noqa: F401

config = NetBoxGuardConfig
