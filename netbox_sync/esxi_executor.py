"""Adapt one ESXi SourceConfig into the shared discovered-source pipeline."""

from .esxi_client import EsxiClient
from .esxi_discovery import discover_hosts


def execute_esxi_source(
        source_config,
        sync_mode,
        reconcile,
        client=None,
):
    """Discover ESXi inventory and invoke the existing generic reconciliation."""

    if source_config.source_type != 'esxi':
        raise ValueError('ESXi executor requires source_type=esxi')
    if source_config.legacy_identity_owner:
        raise ValueError('ESXi source cannot own legacy Proxmox identities')
    from .scheduled_failure import mark
    mark('provider')
    api_client = client or EsxiClient()
    with api_client.session(source_config) as service_instance:
        hosts = discover_hosts(service_instance, source_config)
    return reconcile(source_config, hosts, sync_mode)
