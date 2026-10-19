from .vm_network_writes import write_vm_networks
from .vm_network_report import print_vm_network_precheck
from .vm_network_inventory import prepare_vm_network_inventory
from .netbox_record_values import object_id as _object_id
from .interface_display import interface_display_name, validate_interface_names
from .host_mapping import cluster_filter
import ipaddress
from .network_scopes import scope_key,object_id as scope_object_id

from .netbox_vm_metadata import (
    find_vm_sync_identity_matches,
)

from .netbox_vm_interface_metadata import (
    MANAGED_VM_INTERFACE_CUSTOM_FIELDS,
    build_nic_custom_fields,
    find_nic_sync_identity_matches,
    nic_identity_source_id,
)


from .vm_network_preflight import (
    VMNetworkApplyError,
    ManagedMACConflict,
    _canonical_mac,
    _usable_address,
    _assigned_object,
    _find_vm,
    _interface_match,
    _desired_interface_changes,
    _current_primary_mac_id,
    _current_primary_ip_id,
    _primary_ip_belongs_to_vm,
    prepare_vm_network_contexts,
)


def resolve_vm_network_target(config):
    """Resolve target fields from SourceConfig or the legacy flat target."""

    target = getattr(config, 'target', None) or config
    try:
        return target.site_slug, target.cluster_name
    except AttributeError as exc:
        raise VMNetworkApplyError(
            'VM network target configuration is incomplete'
        ) from exc


def apply_vm_networks(
        nb_api,
        hosts,
        config,
        *,
        confirmed=False,
):
    site_slug, cluster_name = resolve_vm_network_target(config)
    site = nb_api.dcim.sites.get(
        slug=site_slug
    )

    if site is None:
        raise VMNetworkApplyError(
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
        raise VMNetworkApplyError(
            'Expected exactly one '
            'target cluster'
        )

    cluster = cluster_matches[0]

    inventory = prepare_vm_network_inventory(nb_api, cluster, _canonical_mac=_canonical_mac)
    contexts = prepare_vm_network_contexts(hosts, inventory)

    print_vm_network_precheck(contexts, site, cluster)

    if not confirmed:
        print(
            'APPLY_CONFIRM=VM_NETWORK_WRITE '
            'is not set.'
        )
        print(
            'No changes were written '
            'to NetBox.'
        )
        return

    write_vm_networks(nb_api, contexts)
