"""Review enrichment retains allowlists and provider-kind occurrence matching."""

import json
import pytest
from dataclasses import replace
from netbox_sync.application.discovery_review import build_esxi_review
from netbox_sync.esxi_adoption import AdoptionClassification, AdoptionEvidence, EsxiAdoptionItem, EsxiAdoptionPlan
from netbox_sync.source_identity import SourceIdentity
from tests.sample_data import sample_source_config


from copy import deepcopy
from types import SimpleNamespace as NS
from netbox_sync.application.discovery_review import DiscoveryReview, ReviewItem, ReviewClassification, enrich_review


def item(kind, properties=None):
    return ReviewItem(
        kind, "same", "101", ReviewClassification.CONFLICT, "fixture", "review", "review", properties=properties or {}
    )


def guest(**changes):
    values = dict(source="proxmox", source_instance="source-a", vmid=101, original_name="same", interfaces=[], disks=[])
    values.update(changes)
    return NS(**values)


def review(items, vms=(), containers=()):
    host = NS(
        source="proxmox",
        source_instance="source-a",
        source_id="host",
        original_name="host",
        virtual_machines=list(vms),
        containers=list(containers),
    )
    return enrich_review(DiscoveryReview("source-a", "proxmox", "site", "cluster", tuple(items)), [host])


def test_vm_and_lxc_with_equal_ids_do_not_share_properties():
    result = review([item("lxc"), item("qemu")], [guest(vcpus=2)], [guest(vcpus=4)])
    assert [entry.properties for entry in result.items] == [{"vcpus": 4}, {"vcpus": 2}]


def test_allowlisted_projection_keeps_bounds_fallbacks_and_existing_properties():
    original = item("qemu", {"kept": "original", "memory_bytes": 123})
    obj = guest(
        vcpus=True,
        memory_bytes=-1,
        status="x" * 250,
        cpu=NS(model="m" * 250),
        management_ip="192.0.2.1",
        interfaces=[
            NS(name="eth0", addresses=["192.0.2.2/24", "192.0.2.2/24"], vlan_id=0, mac_address="", bridge=None)
        ],
        disks=[NS(path="disk-a", size_bytes=1), NS(path="empty", size_bytes=0)],
        password="private",
    )
    before = deepcopy(original.properties)
    result = review([original], [obj]).items[0]
    assert result.properties == {
        "kept": "original",
        "memory_bytes": 123,
        "vcpus": True,
        "status": "x" * 200,
        "cpu": "m" * 200,
        "interfaces": [
            {"name": "eth0", "addresses": ["192.0.2.2/24", "192.0.2.2/24"], "mac_address": "", "vlan_id": 0}
        ],
        "addresses": ["192.0.2.1", "192.0.2.2/24"],
        "disks": [{"name": "disk-a", "size_bytes": 1}],
    }
    assert original.properties == before


def test_exhausted_occurrences_preserve_unmatched_item_identity():
    first, second = item("qemu"), item("qemu", {"old": True})
    result = review([first, second], [guest(vcpus=2)])
    assert result.items[0].properties == {"vcpus": 2}
    assert result.items[1] is second


@pytest.mark.parametrize(
    "url,base",
    [("https://netbox.test", "https://netbox.test"), ("https://user:secret@netbox.test", ""), ("file:///private", "")],
)
def test_esxi_candidate_projection_retains_sorting_and_sanitizes_links(url, base):
    config = replace(sample_source_config(), source_type="esxi", legacy_identity_owner=False)
    identity = SourceIdentity("v2", "esxi", config.source_instance, "vm", "vm-1")
    snapshot = json.dumps({"sync_identities": [{"external_id": "b"}, {"source_id": "a"}, None]})
    candidates = (
        AdoptionEvidence(2, "two", ("name",), ("conflict",), snapshot),
        AdoptionEvidence(10, "ten", (), (), "{}"),
    )
    entry = EsxiAdoptionItem("vm", "same", identity, AdoptionClassification.REVIEW_REQUIRED, candidates, 2)
    plan = EsxiAdoptionPlan(config.source_instance, 1, 17, (entry,), netbox_url=url)
    result = build_esxi_review(plan, config).items[0]
    assert result.matched_object_name == "two"
    assert result.properties["matching_candidates"] == [
        {
            "id": 10,
            "name": "ten",
            "url": base + "/virtualization/virtual-machines/10/" if base else "",
            "external_ids": [],
            "signals": [],
            "conflicts": [],
        },
        {
            "id": 2,
            "name": "two",
            "url": base + "/virtualization/virtual-machines/2/" if base else "",
            "external_ids": ["a", "b"],
            "signals": ["name"],
            "conflicts": ["conflict"],
        },
    ]


@pytest.mark.parametrize(
    "in_target,code", [(True, "SELECTEL_HARDWARE_MATCH"), (False, "SELECTEL_PLACEMENT_REVIEW_REQUIRED")]
)
def test_provider_hardware_match_keeps_existing_object_and_scope(monkeypatch, in_target, code):
    from netbox_sync.application.discovery_review import _proxmox_host_item
    from netbox_sync import selectel_host_match

    host = NS(source="proxmox", source_instance="source-a", source_id="host", original_name="same")
    record = NS(id=42, name="provider-name", serialize=lambda: {"custom_fields": {}})
    monkeypatch.setattr(selectel_host_match, "matches", lambda devices, candidate: [record])
    result = _proxmox_host_item(host, [record], [record] if in_target else [])
    assert result.reason_code == code
    assert result.matched_object_id == 42
    assert result.matched_object_name == "provider-name"
