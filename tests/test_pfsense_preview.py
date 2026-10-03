import copy
import json
import pytest
from netbox_sync.pfsense_preview import build_preview, load_snapshot, SnapshotError


def sample():
    snapshot = dict(schema='netbox-sync.pfsense.network.v1', collected_at='2026-10-03T18:58:29Z',
        version='2.7.2-RELEASE', configuration=dict(interfaces=[dict(id='wan', name='WAN',
        device='vtnet0', enabled=True, ipv4_config='192.0.2.9', ipv4_prefix='28',
        ipv6_config='dhcp6', ipv6_prefix='', configured_mtu='')], vlans=[]),
        runtime=dict(ifconfig='vtnet0: flags=1008843<UP,BROADCAST,RUNNING,LOWER_UP> metric 0 mtu 1500\n'
        '\tether bc:24:11:90:8c:32\n'
        '\tinet 192.0.2.9 netmask 0xfffffff0 broadcast 192.0.2.15\n'
        '\tinet 192.0.2.3 netmask 0xfffffff0 broadcast 192.0.2.15\n'
        '\tinet6 fe80::1%vtnet0 prefixlen 64 scopeid 0x1\n'
        '\tmedia: Ethernet autoselect (10Gbase-T <full-duplex>)\n'
        '\tstatus: active\n'
        'lo0: flags=1008049<UP,LOOPBACK,RUNNING> metric 0 mtu 16384\n'
        '\tinet 127.0.0.1 netmask 0x0\n'))
    inventory = [dict(id=17, vm_id=2609, name='vmbr0', mac='BC:24:11:90:8C:32')]
    return snapshot, inventory


def test_addresses_and_names_preserved_without_writes_or_inference():
    snapshot, inventory = sample()
    original = copy.deepcopy((snapshot, inventory))
    result = build_preview(snapshot, inventory, 2609)
    row = result['interfaces'][0]
    assert result['all_interfaces_matched']
    assert result['mode'] == 'READ_ONLY'
    assert row['match'] == dict(id=17, name='vmbr0')
    assert row['configuration']['name'] == 'WAN'
    assert row['runtime']['mtu'] == 1500
    assert [a['address'] for a in row['runtime']['addresses']] == ['192.0.2.9/28', '192.0.2.3/28', 'fe80::1/64']
    assert not row['runtime']['addresses'][2]['ipam_candidate']
    assert row['configuration']['ipv6_config'] == 'dhcp6'
    assert result['unmapped_runtime_devices'] == ['lo0']
    assert original == (snapshot, inventory)


@pytest.mark.parametrize('side', ['netbox', 'runtime'])
def test_duplicate_mac_never_selects_arbitrarily(side):
    snapshot, inventory = sample()
    if side == 'netbox':
        inventory.append(dict(inventory[0], id=18))
    else:
        snapshot['runtime']['ifconfig'] += 'vtnet1: flags=1<UP> metric 0 mtu 1500\n\tether bc:24:11:90:8c:32\n'
    result = build_preview(snapshot, inventory, 2609)
    assert result['issues'][0]['code'] == 'AMBIGUOUS_MAC'
    assert result['interfaces'][0]['match'] is None


def test_no_name_or_ip_fallback():
    snapshot, inventory = sample()
    inventory[0].update(name='WAN', mac='bc:24:11:90:8c:34')
    result = build_preview(snapshot, inventory, 2609)
    assert result['issues'][0]['code'] == 'NO_VM_INTERFACE_MATCH'
    assert result['unmatched_vm_interfaces'] == [17]


def test_foreign_vm_rejected_even_with_matching_mac():
    snapshot, inventory = sample()
    inventory[0]['vm_id'] = 2610
    with pytest.raises(SnapshotError):
        build_preview(snapshot, inventory, 2609)


@pytest.mark.parametrize('case', ['schema', 'date', 'duplicate_device', 'duplicate_id', 'mask', 'truncated', 'scope'])
def test_malformed_snapshot_fails_closed(case):
    snapshot, inventory = sample()
    if case == 'schema': snapshot['schema'] = 'other'
    if case == 'date': snapshot['collected_at'] = 'yesterday'
    if case == 'duplicate_device': snapshot['configuration']['interfaces'] *= 2
    if case == 'duplicate_id': inventory *= 2
    if case == 'mask': snapshot['runtime']['ifconfig'] = snapshot['runtime']['ifconfig'].replace('0xfffffff0', '0xff00ff00')
    if case == 'truncated': snapshot['runtime']['ifconfig'] = 'vtnet0: flags='
    if case == 'scope': snapshot['runtime']['ifconfig'] = snapshot['runtime']['ifconfig'].replace('%vtnet0', '%vtnet9')
    with pytest.raises(SnapshotError):
        build_preview(snapshot, inventory, 2609)


def test_missing_runtime_interface_is_explicit():
    snapshot, inventory = sample()
    snapshot['configuration']['interfaces'][0]['device'] = 'missing0'
    result = build_preview(snapshot, inventory, 2609)
    assert result['issues'][0]['code'] == 'RUNTIME_MISSING'


def test_json_duplicate_keys_rejected(tmp_path):
    path = tmp_path / 'snapshot.json'
    path.write_text('{"schema":"one","schema":"two"}')
    with pytest.raises(SnapshotError): load_snapshot(path)


def test_extra_secret_fields_are_not_forwarded():
    snapshot, inventory = sample()
    snapshot['password'] = 'DO_NOT_EXPORT'
    snapshot['configuration']['interfaces'][0]['password'] = 'DO_NOT_EXPORT'
    assert 'DO_NOT_EXPORT' not in json.dumps(build_preview(snapshot, inventory, 2609))
