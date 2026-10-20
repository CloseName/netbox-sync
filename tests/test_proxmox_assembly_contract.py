"""Proxmox host assembly preserves read order and isolated VM/LXC validation."""

import pytest
from netbox_sync.proxmox_discovery import discover_hosts
from tests.fakes import FakeProxmox
from tests.sample_data import proxmox_responses, sample_source_config


@pytest.mark.parametrize(
    "kind,field",
    [
        ("qemu", "sockets"),
        ("qemu", "cores"),
        ("qemu", "vcpus"),
        ("qemu", "memory"),
        ("lxc", "cores"),
        ("lxc", "memory"),
        ("lxc", "swap"),
    ],
)
def test_negative_resource_rejects_only_its_workload(kind, field):
    responses = proxmox_responses()
    responses[("nodes", "node-a", kind, 100, "config")][field] = -1
    host = discover_hosts(FakeProxmox(responses), sample_source_config())[0]
    assert len(host.virtual_machines) == (0 if kind == "qemu" else 1)
    assert len(host.containers) == (0 if kind == "lxc" else 1)


def test_host_reads_precede_guest_config_and_network_read_is_shared():
    api = FakeProxmox(proxmox_responses())
    host = discover_hosts(api, sample_source_config())[0]
    paths = [path for path, params in api.calls]
    assert paths[:5] == [
        ("cluster", "status"),
        ("nodes",),
        ("nodes", "node-a", "status"),
        ("nodes", "node-a", "storage"),
        ("nodes", "node-a", "network"),
    ]
    assert paths.count(("nodes", "node-a", "network")) == 1
    assert paths.index(("nodes", "node-a", "qemu", 100, "config")) < paths.index(
        ("nodes", "node-a", "lxc", 100, "config")
    )
    assert host.virtual_machines[0].vmid == host.containers[0].vmid == 100
    assert host.virtual_machines[0].source_id != host.containers[0].source_id
