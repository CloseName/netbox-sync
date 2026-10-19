"""VLAN choice and bridge output through the complete VM planner."""
import pytest
from tests.fakes import FakeRecord
from tests.test_esxi_network_bootstrap import _managed_setup
from netbox_sync.netbox_vm_network_planner import plan_vm_networks


@pytest.mark.parametrize('scenario', ['absent', 'missing', 'global', 'site', 'prefer_site',
                                     'foreign', 'ambiguous_site', 'ambiguous_global', 'zero'])
@pytest.mark.parametrize('bridge', [None, 'vmbr-test'])
def test_vlan_bridge_output_and_continuation(fake_netbox, capsys, scenario, bridge):
    cluster, target, hosts, _, _ = _managed_setup(fake_netbox)
    site = fake_netbox.dcim.sites.get(slug=target.site_slug)
    nic = hosts[0].virtual_machines[0].interfaces[0]
    nic.bridge = bridge
    nic.vlan_id = None if scenario == 'absent' else (0 if scenario == 'zero' else 120)
    # Make prefix selection deterministic so warnings below count VLAN only.
    fake_netbox.ipam.prefixes.add(FakeRecord(id=900, prefix='192.0.2.0/24'))
    scopes = {
        'absent': [], 'missing': [], 'global': [(None, None)],
        'site': [('dcim.site', site.id)],
        'prefer_site': [(None, None), (None, None), ('dcim.site', site.id)],
        'foreign': [('dcim.site', 999)],
        'ambiguous_site': [('dcim.site', site.id), ('dcim.site', site.id), (None, None)],
        'ambiguous_global': [(None, None), (None, None)], 'zero': [(None, None)],
    }[scenario]
    for identity, (scope_type, scope_id) in enumerate(scopes, 801):
        fake_netbox.ipam.vlans.add(FakeRecord(id=identity, vid=nic.vlan_id,
            scope_type=scope_type, scope_id=scope_id))
    if scenario == 'absent':
        expected = '        vlan=-'
    elif scenario in ('missing', 'foreign'):
        expected = '        WARN VLAN vid=120 not-found action=not-created'
    elif scenario.startswith('ambiguous'):
        expected = '        WARN VLAN vid=120 ambiguous action=not-set'
    else:
        identity = 803 if scenario == 'prefer_site' else 801
        expected = f'        MATCH VLAN id={identity} vid={nic.vlan_id}'
    capsys.readouterr()
    plan_vm_networks(fake_netbox, hosts[0], cluster, site)
    lines = capsys.readouterr().out.splitlines()
    bridge_line = f'        bridge={bridge or "-"}'
    assert [line for line in lines if 'bridge=' in line] == [bridge_line]
    assert [line for line in lines if ' VLAN ' in line or 'vlan=' in line] == [expected]
    assert lines.index(expected) == lines.index(bridge_line) + 1
    assert lines.index(expected) < next(i for i, line in enumerate(lines) if 'CREATE MAC ' in line)
    assert lines.index(expected) < next(i for i, line in enumerate(lines) if 'CREATE IP ' in line)
    warnings = int(scenario in ('missing', 'foreign', 'ambiguous_site', 'ambiguous_global'))
    assert f'      warnings={warnings}' in lines
    assert '    VM NETWORK PLAN SUMMARY' in lines
    assert fake_netbox.mutations == []
