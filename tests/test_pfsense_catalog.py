"""Identity and isolated search contracts, without a live appliance."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('catalog', Path(__file__).parents[1] / 'deploy/netbox_guard/pfsense_catalog_policy.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


def test_rule_identity_survives_reorder_and_change():
    first = {'order': 1, 'tracker': ['123'], 'descr': ['web'], 'destination/address': ['10.0.0.1']}
    second = {**first, 'order': 5, 'destination/address': ['10.0.0.2']}
    assert catalog.identity('firewall', 'rules', first) == catalog.identity('firewall', 'rules', second)


def test_anonymous_nat_identity_ignores_order_but_not_configuration():
    row = {'order': 1, 'target': ['10.0.0.1']}
    assert catalog.identity('nat', 'outbound', row) == catalog.identity('nat', 'outbound', {**row, 'order': 4})
    assert catalog.identity('nat', 'outbound', row) != catalog.identity('nat', 'outbound', {**row, 'target': ['10.0.0.2']})


def test_alias_resolution_is_scoped_recursive_and_cycle_safe():
    aliases = {'LAN': ['10.160.0.0/16', 'nested'], 'nested': ['LAN', '192.0.2.10']}
    row = {'destination/address': ['LAN'], 'destination/not': [''], 'destination/port': ['443']}
    reasons = catalog.match('10.160.0.9', row, aliases)
    assert reasons and any('LAN' in r for r in reasons)
    assert catalog.match('443', row, aliases)
    assert not catalog.match('10.160.0.9', row, {})
    assert not catalog.match('10.160.0.9', {'descr': ['10.160.0.90']}, {})


def test_addresses_networks_ranges_ipv6_and_partial_text():
    assert catalog.match('2001:db8::1', {'source/address': ['2001:db8::/64']}, {})
    assert catalog.match('10.0.0.4', {'source/address': ['10.0.0.1-10.0.0.9']}, {})
    assert not catalog.match('10.0.0.40', {'source/address': ['10.0.0.1-10.0.0.9']}, {})
    assert catalog.match('web', {'descr': ['Web access']}, {})
    assert not catalog.match('10.0.0.0/24', {'source/address': ['10.0.0.1']}, {})
