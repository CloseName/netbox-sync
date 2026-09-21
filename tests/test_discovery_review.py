"""Provider-neutral review mapping keeps existing identity and review semantics."""

from dataclasses import replace
from types import SimpleNamespace

from netbox_sync.application.discovery_review import build_esxi_review, build_proxmox_review
from netbox_sync.esxi_adoption import (AdoptionClassification, AdoptionEvidence,
                                           EsxiAdoptionItem, EsxiAdoptionPlan)
from netbox_sync.source_identity import SourceIdentity
from tests.sample_data import sample_source_config


class Endpoint:
    def __init__(self, values=()):
        self.values = values

    def all(self):
        return self.values

    def get(self, **_kwargs):
        return self.values[0] if self.values else None

    def filter(self, **_kwargs):
        return self.values

    def create(self, *_args, **_kwargs):
        raise AssertionError('NetBox POST is forbidden during discovery')

    def update(self, *_args, **_kwargs):
        raise AssertionError('NetBox PATCH/PUT is forbidden during discovery')

    def delete(self, *_args, **_kwargs):
        raise AssertionError('NetBox DELETE is forbidden during discovery')


def test_proxmox_identity_name_and_new_classification():
    config = sample_source_config()
    host = SimpleNamespace(source='proxmox', source_instance=config.source_instance,
                           source_id='node-a', original_name='node-a', virtual_machines=[], containers=[])
    identity_record = {'schema': 'v2', 'type': 'proxmox', 'instance': config.source_instance,
                       'kind': 'host', 'external_id': 'node-a'}
    site = SimpleNamespace(id=10)
    cluster_type = SimpleNamespace(id=11)
    cluster = SimpleNamespace(id=12, serialize=lambda: {
        'type': 11, 'scope_type': 'dcim.site', 'scope_id': 10})
    managed = SimpleNamespace(id=1, name='old-name', serialize=lambda: {
        'name': 'old-name', 'site': 10, 'cluster': 12,
        'custom_fields': {'sync_identities': [identity_record]}})
    nb_api = SimpleNamespace(dcim=SimpleNamespace(devices=Endpoint([managed]), sites=Endpoint([site])),
                             virtualization=SimpleNamespace(virtual_machines=Endpoint(),
                                                            cluster_types=Endpoint([cluster_type]),
                                                            clusters=Endpoint([cluster])))
    review = build_proxmox_review(nb_api, [host], config)
    assert review.items[0].classification.value == 'MANAGED'
    assert review.items[0].future_action == 'none'


def test_proxmox_management_ip_is_review_evidence_not_ownership():
    config = sample_source_config()
    host = SimpleNamespace(
        source='proxmox', source_instance=config.source_instance,
        source_id='node-a', original_name='node-a', management_ip='10.20.30.10',
        virtual_machines=[], containers=[],
    )
    site = SimpleNamespace(id=10)
    cluster_type = SimpleNamespace(id=11)
    cluster = SimpleNamespace(id=12, serialize=lambda: {
        'type': 11, 'scope_type': 'dcim.site', 'scope_id': 10,
    })
    candidate = SimpleNamespace(
        id=20, name='OTHER-HOST', primary_ip4='10.20.30.10/24',
        serialize=lambda: {
            'name': 'OTHER-HOST', 'site': 10, 'cluster': 12,
            'primary_ip4': '10.20.30.10/24', 'custom_fields': {},
        },
    )
    nb_api = SimpleNamespace(
        dcim=SimpleNamespace(devices=Endpoint([candidate]), sites=Endpoint([site])),
        virtualization=SimpleNamespace(
            virtual_machines=Endpoint(), cluster_types=Endpoint([cluster_type]),
            clusters=Endpoint([cluster]),
        ),
    )

    item = build_proxmox_review(nb_api, [host], config).items[0]

    assert item.classification.value == 'REVIEW_REQUIRED'
    assert item.reason_code == 'MANAGEMENT_IP_CANDIDATE'
    assert item.matched_object_id == 20


def test_esxi_review_required_is_preserved_and_never_becomes_adoption():
    config = replace(sample_source_config(), source_type='esxi', legacy_identity_owner=False)
    identity = SourceIdentity('v2', 'esxi', config.source_instance, 'vm', 'vm-1')
    evidence = AdoptionEvidence(61, 'legacy-vm', ('exact_name',), (), '{}')
    plan = EsxiAdoptionPlan(config.source_instance, 1, 17, (EsxiAdoptionItem(
        'vm', 'legacy-vm', identity, AdoptionClassification.REVIEW_REQUIRED,
        (evidence,), 61),))
    item = build_esxi_review(plan, config).items[0]
    assert item.classification.value == 'REVIEW_REQUIRED'
    assert item.reason_code == 'LEGACY_REVIEW_REQUIRED'
    assert item.future_action == 'review'


def test_inventory_properties_survive_worker_projection_without_collapsing_duplicate_ids():
    from dataclasses import asdict
    from netbox_sync.application.discovery_review import DiscoveryReview, ReviewItem, ReviewClassification, enrich_review
    from netbox_sync.api.dto import DiscoveryResultDTO
    objects=[]
    for index in range(2):
        objects.append(SimpleNamespace(source='esxi',source_instance='esxi-test',vmid='shared',external_id='shared',original_name='same-name',
            vcpus=2+index,memory_bytes=1024**3,status='running',disks=[SimpleNamespace(name='disk0',size_bytes=20*1024**3)],
            interfaces=[SimpleNamespace(name='eth0',ip_addresses=[f'192.0.2.{index+1}/24'],mac_address=None,bridge=None,vlan_id=None)],
            description='DO_NOT_PROJECT_DESCRIPTION'))
    host=SimpleNamespace(source='esxi',source_instance='esxi-test',source_id='host',original_name='host',virtual_machines=objects,containers=[])
    items=tuple(ReviewItem('vm','same-name','shared',ReviewClassification.CONFLICT,'VM_IDENTITY','conflict','review') for _ in objects)
    review=enrich_review(DiscoveryReview('esxi-test','esxi','site','cluster',items),[host])
    dto=DiscoveryResultDTO.from_worker(asdict(review))
    assert [row.properties.vcpus for row in dto.items]==[2,3]
    assert dto.items[1].properties.addresses==['192.0.2.2/24']
    assert dto.items[0].properties.disks[0].size_bytes==20*1024**3
    assert 'DO_NOT_PROJECT_DESCRIPTION' not in dto.model_dump_json()
