"""Missing target clusters block guest planning without reads or writes."""
import pytest
from netbox_sync.netbox_vm_planner import plan_virtual_machines
from netbox_sync.netbox_vm_network_planner import plan_vm_networks
from netbox_sync.netbox_lxc_planner import plan_lxc_containers
from netbox_sync.netbox_planner import plan_hosts
from tests.test_host_apply_preflight_contract import prepared


@pytest.mark.parametrize('planner,title', [
    (plan_virtual_machines, 'QEMU VIRTUAL MACHINES'),
    (plan_vm_networks, 'QEMU VM NETWORK'),
    (plan_lxc_containers, 'LXC CONTAINERS'),
])
def test_missing_cluster_blocks_before_inventory(planner, title, capsys):
    class NoReads:
        def __getattr__(self, name):
            pytest.fail(f'Unexpected read: {name}')
    args = [NoReads(), NoReads(), None]
    if planner is plan_vm_networks:
        args.append(NoReads())
    assert planner(*args) is None
    assert capsys.readouterr().out == f'\n  {title}\n    BLOCKED target cluster does not exist\n'


def test_missing_cluster_reports_every_host_and_never_queries_guests(fake_netbox, monkeypatch, capsys):
    config, hosts = prepared(fake_netbox)
    fake_netbox.virtualization.clusters.records.clear()
    def forbidden(*args, **kwargs):
        pytest.fail('Guest inventory must not be read without a cluster')
    monkeypatch.setattr(fake_netbox.virtualization.virtual_machines, 'filter', forbidden)
    assert plan_hosts(fake_netbox, {'devices': {}}, hosts, config) is None
    output = capsys.readouterr().out
    assert output.count('CREATE CLUSTER') == 1
    assert output.count('HOST source=') == 2
    assert output.count('BLOCKED target cluster does not exist') == 6
    assert fake_netbox.mutations == []
