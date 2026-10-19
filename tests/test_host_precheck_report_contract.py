"""Exact host precheck output before extracting the reporter."""
from pathlib import Path
import pytest
from tests.fakes import FakeRecord
from tests.test_host_apply_preflight_contract import prepared
from netbox_sync.netbox_metadata import build_device_custom_fields
from netbox_sync.netbox_apply import apply_hosts


@pytest.mark.parametrize('scenario', ['empty', 'create', 'match', 'changed', 'mixed', 'network_disabled'])
def test_exact_precheck_output_without_confirmation(fake_netbox, capsys, scenario):
    config, hosts = prepared(fake_netbox)
    if scenario != 'mixed':
        hosts = hosts[:1]
    if scenario == 'empty':
        hosts = []
    if scenario in ('match', 'changed', 'mixed'):
        fields = build_device_custom_fields(hosts[0], {})
        if scenario == 'changed':
            fields['cpu_model'] = 'old-model'
            fields['memory_mb'] = -1
        fake_netbox.dcim.devices.add(FakeRecord(id=801, name=hosts[0].normalized_name,
            site=1, custom_fields=fields))
    capsys.readouterr()
    apply_hosts(fake_netbox, hosts, config, confirmed=False,
                host_networking=scenario != 'network_disabled')
    output = capsys.readouterr().out
    snapshot = Path(__file__).parent / 'fixtures' / 'host_precheck_reports' / (scenario + '.txt')
    assert output == snapshot.read_text(encoding='utf-8')
    assert output.endswith('PRECHECK PASSED\nAPPLY_CONFIRM=HOST_WRITE is not set.\nNo changes were written to NetBox.\n')
    assert fake_netbox.mutations == []
