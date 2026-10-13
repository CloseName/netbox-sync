import copy
import importlib.util
from pathlib import Path
import unittest
from tests.resource_registry_fixture import fixture

spec = importlib.util.spec_from_file_location('registry_policy',
    Path(__file__).resolve().parents[1] / 'deploy/netbox_guard/resource_registry_policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class RegistryPolicyTests(unittest.TestCase):
    def test_failure_retains_success_and_recovery_replaces(self):
        d = fixture(); original = copy.deepcopy(d)
        first = policy.merge(None, policy.normalize(d))
        self.assertEqual(d, original)
        key = d['resources'][-1]['key']
        d['resources'][-1]['observations'][1].update(status='HTTP_403', data=[])
        d['observed_at'] = '2026-10-13T11:00:00Z'
        second = policy.merge(first, policy.normalize(d))
        section = second['resources'][key]['sections']['container_options']
        self.assertTrue(section['retained'])
        self.assertEqual(section['latest_status'], 'HTTP_403')
        self.assertEqual(section['data'], [{'general': {'type': 'private'}}])
        self.assertEqual(section['last_success'], original['observed_at'])
        recovered = policy.merge(second, policy.normalize(original))
        self.assertFalse(recovered['resources'][key]['sections']['container_options']['retained'])

    def test_missing_resources_and_edges_retained(self):
        d = fixture(); first = policy.merge(None, policy.normalize(d))
        d['resources'] = d['resources'][:1]; d['relations'] = []
        second = policy.merge(first, policy.normalize(d))
        self.assertEqual(len(second['resources']), 3)
        self.assertEqual(len(second['relations']), 2)
        self.assertEqual(sum(not n['present_in_latest'] for n in second['resources'].values()), 2)

    def test_invalid_scope_conflict_and_extra_data_rejected(self):
        for mutate in (
            lambda d: d.update(account='999'),
            lambda d: d['resources'][-1].update(conflicting_sections=['buckets']),
            lambda d: d['resources'][-1]['observations'][0]['data'].update(password='hidden'),
            lambda d: d['relations'][0].update(relation='physical_cable'),
            lambda d: d['relations'][0].update(source=d['resources'][-1]['key']),
            lambda d: d['resources'].append(copy.deepcopy(d['resources'][-1])),
        ):
            d = fixture(); mutate(d)
            with self.assertRaises(ValueError):
                policy.normalize(d)

    def test_repeat_merge_is_noop(self):
        incoming = policy.normalize(fixture())
        first = policy.merge(None, incoming)
        self.assertEqual(first, policy.merge(first, incoming))
