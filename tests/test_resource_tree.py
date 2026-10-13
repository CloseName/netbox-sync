import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location('resource_tree', Path(__file__).parents[1] / 'deploy/netbox_guard/resource_tree.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ResourceTreeTests(unittest.TestCase):
    def test_project_identity_is_not_name_and_regions_remain_distinct(self):
        def resource(kind, project, region='', native='x'):
            return dict(key=json.dumps(['selectel', '123', project, region, kind, '', native]),
                        kind=kind, name='same-name')
        rows, tree = module.build_tree([
            resource('project', 'p1'), resource('project', 'p2'),
            resource('storage_container', 'p1', 'r1'),
            resource('storage_container', 'p1', 'r2'),
            resource('storage_container', 'p2', 'r1')], revision=3)
        self.assertEqual(len(tree), 2)
        self.assertEqual(len({r['ref'] for r in rows}), 3)
        self.assertEqual([p['count'] for p in tree], [2, 1])
        self.assertTrue(all('revision=3' in r['href'] for r in rows))

    def test_server_without_project_is_not_assigned_to_existing_project(self):
        server = SimpleNamespace(provider_key='server-key', observed_at='now', snapshot={
            'identity': {'kind': 'dedicated', 'native_id': 'id'},
            'sections': {'resource': {'data': {'user_desc': 'host'}}}})
        rows, tree = module.build_tree([], [server])
        self.assertEqual(tree[0]['id'], '')
        self.assertEqual(rows[0]['name'], 'host')
        self.assertIsNone(rows[0]['present_in_latest'])
        self.assertNotIn('revision=', rows[0]['href'])


if __name__ == '__main__':
    unittest.main()
