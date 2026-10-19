from .lxc_network_writes import write_lxc_networks
from .lxc_network_report import print_lxc_network_precheck
from .lxc_network_inventory import prepare_lxc_network_inventory
from .netbox_record_values import object_id as _object_id
from .interface_display import interface_display_name, validate_interface_names
from .host_mapping import cluster_filter
import ipaddress
from .network_scopes import scope_key,object_id as scope_object_id

from .netbox_lxc_metadata import (
    find_lxc_sync_identity_matches,
)

from .netbox_vm_interface_metadata import (
    MANAGED_VM_INTERFACE_CUSTOM_FIELDS,
    build_nic_custom_fields,
    find_nic_sync_identity_matches,
)


from .lxc_network_preflight import (
    LXCNetworkApplyError,
    _canonical_mac,
    _canonical_ip,
    _usable_ip,
    _assigned_object,
    _find_lxc_vm,
    _find_interface,
    _interface_changes,
    _primary_mac_id,
    _primary_ip4_id,
    prepare_lxc_network_contexts,
)


def apply_lxc_networks(
    nb_api,
    hosts,
    config,
    *,
    confirmed=False,
):
    site = nb_api.dcim.sites.get(
        slug=config.site_slug
    )

    if site is None:
        raise LXCNetworkApplyError(
            'Target site not found'
        )

    cluster_matches = list(
        nb_api.virtualization
        .clusters
        .filter(
            **cluster_filter(config)
        )
    )

    cluster_matches = [
        cluster
        for cluster in cluster_matches
        if (
            cluster.serialize().get(
                'scope_type'
            ) == 'dcim.site'
            and cluster.serialize().get(
                'scope_id'
            ) == site.id
        )
    ]

    if len(cluster_matches) != 1:
        raise LXCNetworkApplyError(
            'Expected exactly one '
            'target cluster'
        )

    cluster = cluster_matches[0]

    inventory = prepare_lxc_network_inventory(
        nb_api, _canonical_mac=_canonical_mac, _canonical_ip=_canonical_ip,
    )
    contexts = prepare_lxc_network_contexts(hosts, inventory, cluster)

    print_lxc_network_precheck(contexts, site, cluster)

    if not confirmed:
        print(
            'APPLY_CONFIRM='
            'LXC_NETWORK_WRITE '
            'is not set.'
        )

        print(
            'No changes were written '
            'to NetBox.'
        )

        return

    write_lxc_networks(nb_api, contexts)
