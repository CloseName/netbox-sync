import copy
import unittest

from tools.selectel_audit.field_contract import (
    CUSTOM_FIELDS, ownership_review, resource_key, schema_plan,
)
from tools.selectel_audit.review import addresses, ip, match_candidates


class ContractTests(unittest.TestCase):
    def row(self, **updates):
        return dict({'account': 'synthetic-account', 'provider_id': 'native-id',
                     'project': 'project-a', 'region': 'region-a',
                     'kind': 'dedicated_resource'}, **updates)

    def test_dedicated_key_survives_project_and_region_move(self):
        self.assertEqual(resource_key(self.row()),
                         resource_key(self.row(project='project-b', region='region-b')))
        self.assertNotEqual(resource_key(self.row()), resource_key(self.row(account='other')))

    def test_cloud_keys_require_and_isolate_scope(self):
        row = self.row(kind='cloud_vm')
        self.assertNotEqual(resource_key(row), resource_key(dict(row, project='other')))
        with self.assertRaises(ValueError):
            resource_key(dict(row, region=''))

    def test_candidates_never_grant_authority_even_with_strong_hints(self):
        row = self.row(candidates=[{'id': 1}], match_status='REVIEW_REQUIRED')
        result = ownership_review(row)
        self.assertFalse(result['write_authorized'])
        self.assertEqual(result['binding_status'], 'not_confirmed')
        self.assertIn('Device ID', result['prerequisite'])

    def test_cloud_has_no_invented_physical_hypervisor_parent(self):
        result = ownership_review(self.row(kind='cloud_vm'))
        self.assertEqual(result['hierarchy'], ['Selectel / аккаунт', 'Проект / регион', 'Облачная VM'])

    def test_schema_creation_is_idempotent_and_does_not_mutate_input(self):
        initial = schema_plan([])
        self.assertEqual([x['action'] for x in initial], ['create', 'create'])
        existing = [x['definition'] for x in initial]
        before = copy.deepcopy(existing)
        self.assertEqual([x['action'] for x in schema_plan(existing)], ['unchanged', 'unchanged'])
        self.assertEqual(before, existing)
        self.assertEqual(tuple(existing), CUSTOM_FIELDS)

    def test_incompatible_schema_blocks_instead_of_overwriting(self):
        existing = copy.deepcopy(list(CUSTOM_FIELDS))
        existing[0]['type'] = 'text'
        existing[1]['object_types'].append('dcim.site')
        result = schema_plan(existing)
        self.assertEqual([x['action'] for x in result], ['conflict', 'conflict'])
        self.assertIn('type', result[0]['differences'])
        self.assertIn('object_types', result[1]['differences'])
        with self.assertRaises(ValueError):
            schema_plan(None)

    def test_unknown_scope_cannot_generate_provider_identity(self):
        result = ownership_review(self.row(kind='cloud_vm', region=''))
        self.assertIsNone(result['provider_key'])
        self.assertFalse(result['write_authorized'])


class AddressEvidenceTests(unittest.TestCase):
    def test_placeholders_and_local_addresses_are_not_identity_evidence(self):
        for value in ('0.0.0.0', '::', '127.0.0.1', '::1', '169.254.1.2',
                      'fe80::1', '224.0.0.1', 'ff02::1', '255.255.255.255'):
            with self.subTest(value=value):
                self.assertIsNone(ip(value))

    def test_real_scoped_addresses_remain_available(self):
        for value in ('10.182.1.2', '100.64.1.2', 'fd00::1', '8.8.8.8'):
            self.assertEqual(ip(value), value)

    def test_nova_placeholder_does_not_hide_fixed_ip(self):
        self.assertEqual(addresses({'accessIPv4': '0.0.0.0', 'accessIPv6': '::',
                                    'addresses': {'lan': [{'addr': '10.1.2.3'}]}}), {'10.1.2.3'})

    def test_old_snapshot_placeholder_does_not_match(self):
        rows = [{'kind': 'cloud_vm', 'name': 'cloud-server', 'serial': '',
                 'addresses': ['0.0.0.0'], 'candidates': []}]
        netbox = {'datasets': {'vms': [{'id': 1, 'name': 'different-server',
                                        'primary_ip4': {'address': '0.0.0.0/32'}}]},
                  'coverage': [{'status': 'collected'}]}
        self.assertEqual(match_candidates(rows, netbox)[0]['match_status'], 'NO_CANDIDATE')
