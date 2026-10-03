from datetime import datetime, timezone, timedelta
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest
from netbox_sync.pfsense_preview import build_preview
from tests.test_pfsense_preview import sample

spec = importlib.util.spec_from_file_location('pfsense_network', Path(__file__).parents[1] / 'deploy/netbox_guard/pfsense_network.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NOW = datetime(2026, 10, 3, 19, 0, tzinfo=timezone.utc)


def preview():
    snapshot, inventory = sample()
    return build_preview(snapshot, inventory, 2609)


def test_snapshot_preserves_observations_and_identical_import_is_noop():
    value = module.snapshot_record(preview(), now=NOW)
    original = deepcopy(value)
    assert module.snapshot_record(preview(), value, now=NOW + timedelta(days=1)) is value
    assert value == original
    assert value['schema'] == module.SCHEMA
    assert len(value['interfaces'][0]['runtime']['addresses']) == 3


@pytest.mark.parametrize('case', ['old', 'future', 'ambiguous', 'foreign', 'conflict'])
def test_rejects_unsafe_replacement(case):
    p = preview()
    existing = None
    if case == 'old': p['collected_at'] = '2026-10-03T18:00:00Z'
    if case == 'future': p['collected_at'] = '2026-10-03T20:00:00Z'
    if case == 'ambiguous': p['all_interfaces_matched'] = False
    if case == 'foreign':
        existing = module.snapshot_record(p, now=NOW)
        existing['vm_id'] = 10
    if case == 'conflict':
        existing = module.snapshot_record(p, now=NOW)
        p['version'] = 'changed'
    with pytest.raises(ValueError): module.snapshot_record(p, existing, now=NOW)


def test_newer_snapshot_updates_without_mutating_previous():
    p = preview()
    old = module.snapshot_record(p, now=NOW)
    copy = deepcopy(old)
    p['collected_at'] = '2026-10-03T19:00:00Z'
    p['interfaces'][0]['runtime']['status'] = 'no carrier'
    new = module.snapshot_record(p, old, now=NOW)
    assert new != old and old == copy


def test_display_keeps_additional_wan_address_and_no_raw_secret_fields():
    value = module.snapshot_record(preview(), now=NOW)
    value['password'] = 'DO_NOT_EXPORT'
    rendered = module.panel(value)
    row = rendered['tables'][0]['rows'][0]
    assert '192.0.2.3/28' in row[7]
    assert 'fe80::1/64' in row[8]
    assert 'DO_NOT_EXPORT' not in str(rendered)
    assert module.panel(None) is None
    assert module.panel({'schema':'unknown'})['tables'] == []
