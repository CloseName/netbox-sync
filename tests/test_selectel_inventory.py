import copy
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from tests.selectel_inventory_fixture import fixture

root = Path(__file__).resolve().parents[1] / 'deploy/netbox_guard'
package = types.ModuleType('_inventory_policy_tests')
package.__path__ = [str(root)]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location(package.__name__ + '.selectel_inventory', root / 'selectel_inventory.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class InventoryTests(unittest.TestCase):
    def test_system_identity_fields_survive_normalization(self):
        doc = fixture()
        source = doc['datasets'][0]['items'][0]
        source.update(serial='SERIAL-1', service_tag='TAG-1',
                      system_uuid='b64f8ef7-5c89-48db-8b2a-886731fa16a4')
        resource = self.normalized(doc)[0]['sections']['resource']['data']
        for field in ('serial', 'service_tag', 'system_uuid'):
            self.assertEqual(resource[field], source[field])

    def normalized(self, data=None):
        return list(mod.Inventory(data or fixture()).normalize().values())

    def test_scoped_joins_and_secret_allowlist(self):
        dedicated, cloud = self.normalized()
        encoded = json.dumps([dedicated, cloud])
        self.assertNotIn('never-export', encoded)
        self.assertNotIn('price', encoded)
        self.assertNotIn('203.0.113.1', encoded)
        self.assertNotIn('192.0.2.3', encoded)
        self.assertEqual(dedicated['sections']['placement']['data']['name'], 'SPB-3')
        self.assertEqual(dedicated['sections']['networks']['data'][0]['vlan'], 1608)
        self.assertEqual(cloud['sections']['hardware']['data']['vcpus'], 2)

    def test_access_denied_retains_last_good_and_original_time(self):
        old = self.normalized()[0]
        doc = fixture()
        doc['finished_at'] = '2026-10-12T14:00:00Z'
        entry = next(d for d in doc['datasets'] if d['kind'] == 'resource_info')
        entry.update(items=[], status='HTTP_403')
        new = mod.merge_snapshot(old, self.normalized(doc)[0])
        hw = new['sections']['hardware']
        self.assertEqual(hw['status'], 'access_denied')
        self.assertEqual(hw['data'], old['sections']['hardware']['data'])
        self.assertTrue(hw['retained'])
        self.assertEqual(hw['data_observed_at'], old['sections']['hardware']['observed_at'])
        again = mod.merge_snapshot(new, self.normalized(doc)[0])
        self.assertEqual(again, new)

    def test_empty_vs_unavailable_and_dependency_failure(self):
        old = self.normalized()[0]
        doc = fixture()
        ips = next(d for d in doc['datasets'] if d['kind'] == 'public_ips')
        ips.update(items=[], status='HTTP_404')
        new = mod.merge_snapshot(old, self.normalized(doc)[0])
        self.assertEqual(new['sections']['public_ips']['status'], 'unavailable')
        self.assertTrue(new['sections']['networks']['retained'])
        ips['status'] = 'collected'
        new = mod.merge_snapshot(old, self.normalized(doc)[0])
        self.assertEqual(new['sections']['public_ips']['status'], 'empty')
        self.assertEqual(new['sections']['public_ips']['data'], [])

    def test_duplicate_conflicting_resources_refused(self):
        doc = fixture()
        duplicate = copy.deepcopy(doc['datasets'][0])
        duplicate['items'][0]['user_desc'] = 'different'
        doc['datasets'].append(duplicate)
        with self.assertRaisesRegex(ValueError, 'RESOURCE_CONFLICT'):
            self.normalized(doc)

    def test_different_project_and_region_produce_separate_keys(self):
        doc = fixture()
        duplicate = copy.deepcopy(next(d for d in doc['datasets'] if d['kind'] == 'servers'))
        duplicate['region'] = 'another'
        doc['datasets'].append(duplicate)
        self.assertEqual(len(mod.Inventory(doc).normalize()), 3)

    def test_unverified_and_naive_timestamp_refused(self):
        doc = fixture()
        doc['account_verified'] = False
        with self.assertRaises(ValueError):
            self.normalized(doc)
        doc['account_verified'] = True
        doc['finished_at'] = '2026-10-12T12:00:00'
        with self.assertRaises(ValueError):
            self.normalized(doc)

    def test_projection_does_not_claim_native_topology(self):
        projected = mod.projection(self.normalized()[0])
        self.assertTrue(all(k.startswith('selectel_') for k in projected))
        self.assertEqual(projected['selectel_location'], 'SPB-3')
        self.assertEqual(projected['selectel_networks'], '192.0.2.2')


if __name__ == '__main__':
    unittest.main()
