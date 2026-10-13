import copy
import unittest
import runpy
from pathlib import Path

module = runpy.run_path(str(Path(__file__).parents[1] / 'deploy/netbox_guard/provider_network_status.py'))
evidence_status, summary = module['evidence_status'], module['summary']


class EvidenceStatusTests(unittest.TestCase):
    def test_complete_guest_path_does_not_confirm_physical_connection(self):
        row = {'relation': 'allocation', 'assignment': {'id': 101},
               'host_path': {'status': 'configured', 'paths': [['bridge-test', 'nic-test']]}}
        before = copy.deepcopy(row)
        status = evidence_status(row)
        self.assertEqual(status['assignment']['code'], 'recorded')
        self.assertEqual(status['host_path']['code'], 'configured')
        self.assertFalse(status['physical']['confirmed'])
        self.assertEqual(row, before)

    def test_disabled_and_duplicate_port_names_never_infer_a_nic(self):
        rows = [{'relation': 'attachment', 'provider_ports': [{'uuid': uid, 'port_name': 'same',
                 'is_enabled': enabled}], 'host_interface': 'unverified-value'}
                for uid, enabled in [('a', True), ('b', False)]]
        for row in rows:
            self.assertEqual(evidence_status(row)['physical']['code'], 'unconfirmed')
        self.assertEqual(summary(rows)['unconfirmed_port_attachments'], 2)
        self.assertEqual(summary(rows)['confirmed_physical_links'], 0)

    def test_partial_missing_and_ambiguous_paths_are_not_counted_as_complete(self):
        rows = [{'relation': 'allocation', 'host_path': {'status': code}}
                for code in ('incomplete', 'ambiguous_names', 'snapshot_missing_or_ambiguous')]
        rows.append({'relation': 'allocation'})
        self.assertEqual(summary(rows)['configured_paths'], 0)
        self.assertEqual(summary(rows)['interface_assignments'], 0)
        for row in rows:
            self.assertEqual(evidence_status(row)['assignment']['code'], 'not_established')

    def test_empty_visibility_has_no_counts(self):
        self.assertTrue(all(v == 0 for v in summary([]).values()))


if __name__ == '__main__':
    unittest.main()
