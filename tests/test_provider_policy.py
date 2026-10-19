"""Pure Guard policy contracts; actual PostgreSQL scenarios are separate."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('provider_policy',
    Path(__file__).resolve().parents[1] / 'deploy/netbox_guard/provider_policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class PolicyTests(unittest.TestCase):
    def identity(self, **kw):
        return dict({'account': 'synthetic', 'kind': 'dedicated', 'native_id': 'server-a',
                     'project': '', 'region': ''}, **kw)

    def test_identity_is_stable_for_dedicated_moves(self):
        self.assertEqual(policy.identity(self.identity(), 'device'),
                         policy.identity(self.identity(project='moved', region='other'), 'device'))
        self.assertNotEqual(policy.identity(self.identity(), 'device'),
                            policy.identity(self.identity(account='other'), 'device'))

    def test_cloud_scope_and_target_are_mandatory(self):
        with self.assertRaises(ValueError):
            policy.identity(self.identity(kind='cloud_vm'), 'vm')
        with self.assertRaises(ValueError):
            policy.identity(self.identity(), 'vm')
        self.assertNotEqual(policy.identity(self.identity(kind='cloud_vm', project='p', region='r'), 'vm'),
                            policy.identity(self.identity(kind='cloud_vm', project='q', region='r'), 'vm'))

    def test_projection_cannot_capture_source_fields(self):
        claims = policy.proposed_claims(self.identity(), 'device')
        self.assertEqual(set(claims), {'custom_fields.selectel_refs', 'custom_fields.selectel_summary'})
        with self.assertRaises(ValueError):
            policy.proposed_claims(dict(self.identity(), site_id=1), 'device')

    def test_serial_requires_explicit_real_value_and_device(self):
        self.assertNotIn('serial', policy.proposed_claims(self.identity(), 'device'))
        self.assertEqual(policy.proposed_claims(self.identity(), 'device', 'SN123')['serial'], 'SN123')
        for invalid in ('', 'unknown', 'n/a', 0):
            with self.assertRaises(ValueError):
                policy.proposed_claims(self.identity(), 'device', invalid)

    def test_digest_ignores_key_order_but_detects_value_change(self):
        self.assertEqual(policy.digest({'a': 1, 'b': 2}), policy.digest({'b': 2, 'a': 1}))
        self.assertNotEqual(policy.digest({'a': 1}), policy.digest({'a': 2}))


if __name__ == '__main__':
    unittest.main()
