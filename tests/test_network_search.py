"""Full addresses outrank textual partials; routes retain their own semantics."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('network_search', Path(__file__).parents[1] / 'deploy/netbox_guard/network_search.py')
search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search)


def test_full_ip_order_and_interface_mask():
    def hit(value, model, field='address'):
        return SimpleNamespace(value=value, object_type=SimpleNamespace(model=model), field=field)
    exact = hit('10.78.12.1/26', 'ipaddress')
    partial = hit('10.78.12.125/26', 'ipaddress')
    prefix = hit('10.78.12.0/26', 'prefix', 'prefix')
    route = hit('10.78.0.0/16', 'vrf', 'selectel_route')
    entries = [partial, route, prefix, exact]
    assert sorted(entries, key=lambda h: search.result_rank('10.78.12.1', h)) == [exact, prefix, route, partial]
    assert search.rank('10.78.12.42', '10.78.12.0/26') < search.rank('10.78.12.42', '10.78.0.0/16')
    assert search.rank('10.78.12.0/26', '10.78.12.0/26') < search.rank('10.78.12.0/26', '10.78.0.0/16')


def test_route_exact_contains_name_and_next_hop():
    entry = dict(name='PAM-DEV-CLOUD', cidr='10.160.0.0/16', next_hop='10.161.1.1')
    for query in ('10.160.0.0/16', '10.160.2.3', '10.160.2.0/24', 'PAM-DEV', '10.161.1.1'):
        assert search.route_matches(query, entry)
    assert not search.route_matches('10.170.1.1', entry)
    assert not search.route_matches('10.160.2.3', entry, exact=True)
    assert search.route_matches('10.160.0.0/16', entry, exact=True)
    assert search.rank('2001:db8::1', '2001:db8::/64')[0] == 1
    assert search.rank('2001:db8::1', '10.0.0.0/8')[0] == 3
