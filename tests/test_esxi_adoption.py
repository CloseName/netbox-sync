"""Safety characterization for legacy ESXi adoption preflight."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from netbox_sync.esxi_adoption import (
    AdoptionClassification,
    EsxiAdoptionError,
    apply_esxi_adoption_plan,
    build_esxi_adoption_plan,
)
from netbox_sync.esxi_discovery import discover_hosts
from netbox_sync.netbox_vm_planner import plan_virtual_machines
from netbox_sync.source_config import SecretReference, SourceCredentials
from netbox_sync.source_identity import virtual_machine_source_identity

from tests.fakes import FakeRecord
from tests.fakes.esxi import fake_esxi_service
from tests.netbox_scenarios import add_target
from tests.sample_data import sample_source_config


def _config(source_instance='esxi-infra-test'):
    password = SecretReference(provider='env', key='ESXI_TEST_PASSWORD')
    return replace(
        sample_source_config(),
        id=source_instance,
        source_instance=source_instance,
        source_type='esxi',
        legacy_identity_owner=False,
        credentials=SourceCredentials.for_password('root', password),
    )


def _inventory(name='APP-VM', ip_address='192.0.2.50'):
    service = fake_esxi_service(vm_name=name)
    network = service.host.vm[0].guest.net[0]
    network.ipConfig.ipAddress[0].ipAddress = ip_address
    network.ipAddress = [ip_address]
    return discover_hosts(service, _config())


def _target(fake_netbox):
    site, _, cluster, _ = add_target(fake_netbox)
    return site, cluster


def _add_ip(fake_netbox, record_id, address):
    return fake_netbox.ipam.ip_addresses.add(
        FakeRecord(id=record_id, address=address)
    )


def _add_vm(
        fake_netbox,
        cluster,
        *,
        record_id,
        name,
        ip_address=None,
        custom_fields=None,
):
    primary_ip = (
        _add_ip(fake_netbox, 1000 + record_id, ip_address)
        if ip_address
        else None
    )
    return fake_netbox.virtualization.virtual_machines.add(FakeRecord(
        id=record_id,
        name=name,
        cluster=cluster,
        primary_ip4=primary_ip,
        custom_fields=custom_fields or {},
    ))


def _item(plan, kind):
    return next(item for item in plan.items if item.object_kind == kind)


def test_exact_name_and_ip_is_safe_candidate(fake_netbox):
    _, cluster = _target(fake_netbox)
    _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name='APP-VM',
        ip_address='192.0.2.50/24',
    )

    plan = build_esxi_adoption_plan(fake_netbox, _inventory(), _config())
    item = _item(plan, 'vm')

    assert item.classification == AdoptionClassification.SAFE_ADOPTION_CANDIDATE
    assert item.candidates[0].signals == ('exact_name', 'ip:192.0.2.50')


def test_changed_name_and_same_ip_is_safe_candidate(fake_netbox):
    _, cluster = _target(fake_netbox)
    _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name='pam management server',
        ip_address='192.0.2.50/24',
    )

    item = _item(
        build_esxi_adoption_plan(
            fake_netbox, _inventory(name='PAM-MGMT1'), _config(),
        ),
        'vm',
    )

    assert item.classification == AdoptionClassification.SAFE_ADOPTION_CANDIDATE
    assert item.candidates[0].signals == ('ip:192.0.2.50',)


def test_same_name_with_conflicting_ip_is_ambiguous(fake_netbox):
    _, cluster = _target(fake_netbox)
    _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name='APP-VM',
        ip_address='192.0.2.99/24',
    )

    item = _item(
        build_esxi_adoption_plan(fake_netbox, _inventory(), _config()),
        'vm',
    )

    assert item.classification == AdoptionClassification.AMBIGUOUS
    assert item.candidates[0].conflicts == ('conflicting_ip',)


def test_duplicate_exact_names_are_ambiguous(fake_netbox):
    _, cluster = _target(fake_netbox)
    for record_id in (10, 11):
        _add_vm(
            fake_netbox,
            cluster,
            record_id=record_id,
            name='app-vm',
        )

    item = _item(
        build_esxi_adoption_plan(fake_netbox, _inventory(), _config()),
        'vm',
    )

    assert item.classification == AdoptionClassification.AMBIGUOUS
    assert {candidate.object_id for candidate in item.candidates} == {10, 11}


def test_no_legacy_signals_is_unmatched(fake_netbox):
    _, cluster = _target(fake_netbox)
    _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name='ANOTHER-VM',
        ip_address='198.51.100.10/24',
    )

    item = _item(
        build_esxi_adoption_plan(fake_netbox, _inventory(), _config()),
        'vm',
    )

    assert item.classification == AdoptionClassification.UNMATCHED
    assert item.candidates == ()


def test_existing_v2_identity_is_managed(fake_netbox):
    _, cluster = _target(fake_netbox)
    hosts = _inventory()
    vm = hosts[0].virtual_machines[0]
    identity = virtual_machine_source_identity(vm)
    _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name='OLD-NAME',
        custom_fields={'sync_identities': [identity.to_record()]},
    )

    item = _item(
        build_esxi_adoption_plan(fake_netbox, hosts, _config()),
        'vm',
    )

    assert item.classification == AdoptionClassification.MANAGED
    assert item.selected_object_id == 10


def test_absent_legacy_mac_does_not_block_ip_candidate(fake_netbox):
    _, cluster = _target(fake_netbox)
    _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name='LEGACY-NAME',
        ip_address='192.0.2.50/24',
    )

    item = _item(
        build_esxi_adoption_plan(fake_netbox, _inventory(), _config()),
        'vm',
    )

    assert item.classification == AdoptionClassification.SAFE_ADOPTION_CANDIDATE
    assert item.candidates[0].signals == ('ip:192.0.2.50',)


def test_mac_is_evidence_only_when_present_on_legacy_object(fake_netbox):
    _, cluster = _target(fake_netbox)
    legacy = _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name='APP-VM',
    )
    interface = fake_netbox.virtualization.interfaces.add(FakeRecord(
        id=20,
        name='Network adapter 1',
        virtual_machine=legacy,
        custom_fields={},
    ))
    fake_netbox.dcim.mac_addresses.add(FakeRecord(
        id=30,
        mac_address='00:50:56:AA:BB:CC',
        assigned_object_type='virtualization.vminterface',
        assigned_object_id=interface.id,
    ))

    item = _item(
        build_esxi_adoption_plan(fake_netbox, _inventory(), _config()),
        'vm',
    )

    assert item.classification == AdoptionClassification.SAFE_ADOPTION_CANDIDATE
    assert item.candidates[0].signals == (
        'exact_name',
        'mac:00:50:56:AA:BB:CC',
    )


def test_name_candidate_and_different_ip_candidate_are_ambiguous(fake_netbox):
    _, cluster = _target(fake_netbox)
    _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name='APP-VM',
        ip_address='198.51.100.10/24',
    )
    _add_vm(
        fake_netbox,
        cluster,
        record_id=11,
        name='RENAMED-APP',
        ip_address='192.0.2.50/24',
    )

    item = _item(
        build_esxi_adoption_plan(fake_netbox, _inventory(), _config()),
        'vm',
    )

    assert item.classification == AdoptionClassification.AMBIGUOUS
    assert {candidate.object_id for candidate in item.candidates} == {10, 11}


def test_case_only_exact_name_requires_review(fake_netbox):
    _, cluster = _target(fake_netbox)
    _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name='app-vm',
    )

    item = _item(
        build_esxi_adoption_plan(fake_netbox, _inventory(), _config()),
        'vm',
    )

    assert item.classification == AdoptionClassification.REVIEW_REQUIRED
    assert item.candidates[0].signals == ('exact_name',)


@pytest.mark.parametrize('legacy_name', (
    'CONFLUENCE', 'OWNCLOUD', 'MOODLE', 'KAYAKO', 'KAYAKOTEST',
    'TESTRAIL', 'YOUTRACK-7',
))
def test_known_legacy_name_only_objects_remain_review_required(
        fake_netbox, legacy_name,
):
    _, cluster = _target(fake_netbox)
    _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name=legacy_name.lower(),
    )

    item = _item(
        build_esxi_adoption_plan(
            fake_netbox, _inventory(name=legacy_name), _config(),
        ),
        'vm',
    )

    assert item.classification == AdoptionClassification.REVIEW_REQUIRED
    assert item.candidates[0].signals == ('exact_name',)


def test_host_requires_target_site_and_cluster_and_matches_ip(fake_netbox):
    site, cluster = _target(fake_netbox)
    primary_ip = _add_ip(fake_netbox, 1100, '192.0.2.10/24')
    fake_netbox.dcim.devices.add(FakeRecord(
        id=100,
        name='LEGACY-ESXI-HOST',
        site=site,
        cluster=cluster,
        primary_ip4=primary_ip,
        custom_fields={},
    ))

    item = _item(
        build_esxi_adoption_plan(fake_netbox, _inventory(), _config()),
        'host',
    )

    assert item.classification == AdoptionClassification.SAFE_ADOPTION_CANDIDATE
    assert item.candidates[0].signals == ('ip:192.0.2.10',)


def test_preflight_never_writes(fake_netbox):
    _, cluster = _target(fake_netbox)
    _add_vm(
        fake_netbox, cluster, record_id=10, name='APP-VM',
    )

    plan = build_esxi_adoption_plan(fake_netbox, _inventory(), _config())

    assert _item(plan, 'vm').classification == (
        AdoptionClassification.REVIEW_REQUIRED
    )
    assert fake_netbox.mutations == []


def test_name_only_esxi_vm_shared_plan_handles_legacy_null_metadata(
        fake_netbox,
        capsys,
):
    _, cluster = _target(fake_netbox)
    existing = _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name='APP-VM',
        custom_fields={
            'sync_identities': None,
            'sync_original_names': None,
            'operator_note': 'preserve me',
        },
    )
    hosts = _inventory()
    adoption = build_esxi_adoption_plan(fake_netbox, hosts, _config())

    plan_virtual_machines(fake_netbox, hosts[0], cluster)

    assert _item(adoption, 'vm').classification == (
        AdoptionClassification.REVIEW_REQUIRED
    )
    assert 'ADOPT CANDIDATE' in capsys.readouterr().out
    assert existing.custom_fields['sync_identities'] is None
    assert existing.custom_fields['sync_original_names'] is None
    assert existing.custom_fields['operator_note'] == 'preserve me'
    assert fake_netbox.mutations == []


def test_preflight_plan_is_immutable(fake_netbox):
    _target(fake_netbox)
    plan = build_esxi_adoption_plan(fake_netbox, _inventory(), _config())

    with pytest.raises(FrozenInstanceError):
        plan.source_instance = 'changed'
    with pytest.raises(FrozenInstanceError):
        plan.items[0].classification = AdoptionClassification.MANAGED


def test_legacy_candidate_outside_target_cluster_is_not_matched(fake_netbox):
    site, cluster = _target(fake_netbox)
    other_cluster = fake_netbox.virtualization.clusters.add(FakeRecord(
        id=4,
        name='Other Cluster',
        type=cluster.type,
        scope_type='dcim.site',
        scope_id=site.id,
    ))
    _add_vm(
        fake_netbox,
        other_cluster,
        record_id=10,
        name='APP-VM',
        ip_address='192.0.2.50/24',
    )

    item = _item(
        build_esxi_adoption_plan(fake_netbox, _inventory(), _config()),
        'vm',
    )

    assert item.classification == AdoptionClassification.UNMATCHED
    assert item.candidates == ()


def test_confirmed_adoption_only_merges_identity_metadata(fake_netbox):
    _, cluster = _target(fake_netbox)
    existing = _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name='app-vm',
        ip_address='192.0.2.50/24',
        custom_fields={
            'operator_note': 'preserve me',
            'legacy_flag': True,
            'sync_identities': None,
            'sync_original_names': {'legacy': 'LEGACY-APP'},
        },
    )
    plan = build_esxi_adoption_plan(fake_netbox, _inventory(), _config())
    item = _item(plan, 'vm')

    with pytest.raises(EsxiAdoptionError, match='explicit confirmation'):
        apply_esxi_adoption_plan(fake_netbox, plan)
    assert fake_netbox.mutations == []

    assert apply_esxi_adoption_plan(fake_netbox, plan, confirmed=True) == 1
    assert existing.name == 'app-vm'
    assert existing.custom_fields['operator_note'] == 'preserve me'
    assert existing.custom_fields['legacy_flag'] is True
    assert existing.custom_fields['sync_original_names']['legacy'] == 'LEGACY-APP'
    assert item.identity.to_record() in existing.custom_fields['sync_identities']
    assert existing.custom_fields['sync_original_names'][
        'esxi/esxi-infra-test/vm'
    ] == 'APP-VM'
    assert fake_netbox.mutations == [(
        'update',
        'virtualization.virtual_machines',
        10,
        {'custom_fields': existing.custom_fields},
    )]


def test_changed_candidate_after_preflight_blocks_all_writes(fake_netbox):
    _, cluster = _target(fake_netbox)
    existing = _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name='APP-VM',
        ip_address='192.0.2.50/24',
    )
    plan = build_esxi_adoption_plan(fake_netbox, _inventory(), _config())
    existing.name = 'CHANGED-AFTER-PREFLIGHT'

    with pytest.raises(EsxiAdoptionError, match='evidence changed'):
        apply_esxi_adoption_plan(fake_netbox, plan, confirmed=True)

    assert fake_netbox.mutations == []
    assert existing.custom_fields == {}


def test_review_only_candidate_is_never_written(fake_netbox):
    _, cluster = _target(fake_netbox)
    existing = _add_vm(
        fake_netbox, cluster, record_id=10, name='APP-VM',
    )
    plan = build_esxi_adoption_plan(fake_netbox, _inventory(), _config())

    assert _item(plan, 'vm').classification == (
        AdoptionClassification.REVIEW_REQUIRED
    )
    assert apply_esxi_adoption_plan(fake_netbox, plan, confirmed=True) == 0
    assert existing.custom_fields == {}
    assert fake_netbox.mutations == []


def test_safe_candidate_applies_while_review_candidate_is_untouched(fake_netbox):
    _, cluster = _target(fake_netbox)
    review = _add_vm(
        fake_netbox, cluster, record_id=10, name='APP-VM',
    )
    safe = _add_vm(
        fake_netbox,
        cluster,
        record_id=11,
        name='LEGACY-SAFE-NAME',
        ip_address='192.0.2.60/24',
    )
    hosts = _inventory()
    second = deepcopy(hosts[0].virtual_machines[0])
    second.external_id = '503c5ad7-aaaa-bbbb-cccc-0123456789ab'
    second.vmid = second.external_id
    second.source_id = f'esxi:{second.external_id}'
    second.original_name = 'RENAMED-SAFE-VM'
    second.normalized_name = second.original_name
    second.interfaces[0].ip_addresses = ['192.0.2.60/24']
    hosts[0].virtual_machines.append(second)

    plan = build_esxi_adoption_plan(fake_netbox, hosts, _config())
    vm_items = [item for item in plan.items if item.object_kind == 'vm']

    assert {item.classification for item in vm_items} == {
        AdoptionClassification.REVIEW_REQUIRED,
        AdoptionClassification.SAFE_ADOPTION_CANDIDATE,
    }
    assert apply_esxi_adoption_plan(fake_netbox, plan, confirmed=True) == 1
    assert review.custom_fields == {}
    assert safe.custom_fields['sync_identities'] == [
        next(
            item.identity.to_record()
            for item in vm_items
            if item.classification
            == AdoptionClassification.SAFE_ADOPTION_CANDIDATE
        )
    ]
    assert [mutation[2] for mutation in fake_netbox.mutations] == [11]


def test_multiple_live_vms_claiming_one_legacy_vm_are_ambiguous(fake_netbox):
    _, cluster = _target(fake_netbox)
    _add_vm(
        fake_netbox,
        cluster,
        record_id=10,
        name='APP-VM',
        ip_address='192.0.2.50/24',
    )
    hosts = _inventory()
    duplicate = deepcopy(hosts[0].virtual_machines[0])
    duplicate.external_id = '503c5ad7-aaaa-bbbb-cccc-0123456789ab'
    duplicate.vmid = duplicate.external_id
    duplicate.source_id = f'esxi:{duplicate.external_id}'
    duplicate.original_name = 'RENAMED-APP'
    hosts[0].virtual_machines.append(duplicate)

    plan = build_esxi_adoption_plan(fake_netbox, hosts, _config())
    items = [item for item in plan.items if item.object_kind == 'vm']

    assert len(items) == 2
    assert all(
        item.classification == AdoptionClassification.AMBIGUOUS
        for item in items
    )
    with pytest.raises(EsxiAdoptionError, match='contains ambiguity'):
        apply_esxi_adoption_plan(fake_netbox, plan, confirmed=True)
    assert fake_netbox.mutations == []


def test_missing_cluster_has_placement_diagnostic(fake_netbox):
    from netbox_sync.worker_failure import diagnostic
    _target(fake_netbox)
    fake_netbox.virtualization.clusters.records.clear()
    with pytest.raises(EsxiAdoptionError) as caught:
        build_esxi_adoption_plan(fake_netbox, _inventory(), _config())
    assert diagnostic(caught.value, 'netbox')['code'] == 'NETBOX_PLACEMENT_MISSING'
    assert fake_netbox.mutations == []


def test_ambiguous_cluster_is_mapping_error_not_network_failure(fake_netbox):
    from netbox_sync.worker_failure import diagnostic
    _, cluster = _target(fake_netbox)
    data = cluster.serialize()
    data['id'] = 999
    fake_netbox.virtualization.clusters.add(FakeRecord(**data))
    with pytest.raises(EsxiAdoptionError) as caught:
        build_esxi_adoption_plan(fake_netbox, _inventory(), _config())
    assert diagnostic(caught.value, 'netbox')['code'] == 'MAPPING_INVALID'


@pytest.mark.parametrize('denied', [False, True])
def test_deleted_cluster_over_http_is_distinct_from_denied_read(fake_netbox, denied):
    from tests.fakes.netbox_http import netbox_http
    from netbox_sync.worker_failure import failure_stage, DiagnosticFailure
    _target(fake_netbox)
    fake_netbox.virtualization.clusters.records.clear()
    requests = []
    with netbox_http(fake_netbox, requests=requests,
                     behavior={'deny_reads': ['virtualization.clusters'] if denied else []}) as (api, _, writes):
        with pytest.raises(DiagnosticFailure) as caught:
            with failure_stage('netbox'):
                build_esxi_adoption_plan(api, _inventory(), _config())
        expected = 'NETBOX_PERMISSION_DENIED' if denied else 'NETBOX_PLACEMENT_MISSING'
        assert caught.value.code == expected
        assert writes == [] and all(method == 'GET' for method, _ in requests)
        assert any('/virtualization/clusters/' in path for _, path in requests)
        assert 'PRIVATE_REMOTE_RESPONSE' not in str(caught.value.diagnostic)
