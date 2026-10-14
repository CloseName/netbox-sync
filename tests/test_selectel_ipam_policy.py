import copy
import importlib
import sys
import types
from pathlib import Path
import unittest
from tests.selectel_ipam_fixture import snapshot

pkg = types.ModuleType('_ipam_policy_tests')
pkg.__path__ = [str(Path(__file__).resolve().parents[1] / 'deploy/netbox_guard')]
sys.modules[pkg.__name__] = pkg
policy = importlib.import_module(pkg.__name__ + '.selectel_ipam_policy')


class IPAMPolicyTests(unittest.TestCase):
    def test_explicit_native_projection(self):
        result = policy.project(snapshot())
        self.assertEqual({o['kind'] for o in result['objects'].values()}, {'ipaddress', 'prefix', 'vlan', 'vlangroup'})
        self.assertEqual({l['relation'] for l in result['links']}, {'allocation', 'subnet', 'attachment'})
        self.assertIsNone(next(l for l in result['links'] if l['relation'] == 'attachment')['evidence']['host_interface'])

    def test_shared_host_allocation_not_interface_mask(self):
        data = snapshot()
        ip = data['sections']['public_ips']['data'][0]
        ip.update(subnet='8.8.4.2/32', netmask='255.255.255.0')
        data['sections']['public_subnets']['data'][0]['subnet'] = '8.8.4.2/32'
        result = policy.project(data)
        self.assertEqual(next(o for o in result['objects'].values() if o['kind'] == 'ipaddress')['fields']['address'], '8.8.4.2/24')
        self.assertEqual(next(o for o in result['objects'].values() if o['kind'] == 'prefix')['fields']['prefix'], '8.8.4.2/32')
        self.assertTrue(result['notes'])

    def test_same_vid_different_service(self):
        data = snapshot()
        local = {'uuid': 'local-a', 'location_uuid': 'spb3', 'network_type': 'local', 'vlan': 1608}
        data['sections']['networks']['data'].append(local)
        data['sections']['ports']['data'][0]['networks'].append(local)
        result = policy.project(data)
        self.assertEqual(sum(o['kind'] == 'vlan' for o in result['objects'].values()), 2)
        self.assertEqual(sum(o['kind'] == 'vlangroup' for o in result['objects'].values()), 2)

    def test_missing_network_no_invented_vlan(self):
        data = snapshot()
        data['sections']['networks']['data'] = []
        data['sections']['ports']['data'] = []
        result = policy.project(data)
        self.assertEqual({o['kind'] for o in result['objects'].values()}, {'ipaddress', 'prefix'})
        self.assertEqual(result['notes'][0]['code'], 'NETWORK_NOT_REPORTED')

    def test_refusals(self):
        for mutate in (
            lambda d: d['sections']['public_ips'].update(retained=True),
            lambda d: d['sections']['public_subnets'].update(status='access_denied'),
            lambda d: d['sections']['public_ips']['data'][0].update(netmask=None),
            lambda d: d['sections']['public_ips']['data'][0].update(resource_uuid='other'),
            lambda d: d['sections']['public_ips']['data'][0].update(network_uuid='other'),
            lambda d: d['sections']['public_ips']['data'][0].update(ip='10.0.0.1'),
            lambda d: d['sections']['networks']['data'][0].update(vlan=0),
        ):
            data = copy.deepcopy(snapshot())
            mutate(data)
            with self.assertRaises(ValueError):
                policy.project(data)


if __name__ == '__main__':
    unittest.main()
