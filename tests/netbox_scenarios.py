"""Reusable NetBox target setup for apply characterization tests."""

from netbox_sync.netbox_planner import NetBoxTargetConfig

from tests.fakes import FakeRecord


def add_target(fake_netbox):
    """Create the prerequisites shared by VM and network apply."""

    from netbox_sync.prerequisites import definition
    if not fake_netbox.extras.custom_fields.filter(name='esxi_host_network'):
        fake_netbox.extras.custom_fields.add(FakeRecord(id=9001, **definition('esxi_host_network')))

    site = fake_netbox.dcim.sites.add(
        FakeRecord(id=1, slug='test-site', name='Test Site')
    )
    cluster_type = fake_netbox.virtualization.cluster_types.add(
        FakeRecord(id=2, slug='proxmox', name='Proxmox')
    )
    cluster = fake_netbox.virtualization.clusters.add(
        FakeRecord(
            id=3,
            name='Test Cluster',
            type=cluster_type,
            scope_type='dcim.site',
            scope_id=site.id,
        )
    )
    config = NetBoxTargetConfig(
        site_slug=site.slug,
        device_role_slug='server',
        platform_slug='proxmox',
        device_type_slug='generic',
        cluster_type_slug=cluster_type.slug,
        cluster_name=cluster.name,
    )

    return site, cluster_type, cluster, config


def vm_identity(source_id='node-a:100'):
    return {
        'sync_identities': [
            {
                'source': 'proxmox',
                'source_id': source_id,
            },
        ],
    }
