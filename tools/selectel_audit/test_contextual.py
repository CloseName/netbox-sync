import copy
import unittest
from tools.selectel_audit.contextual_review import contextual_review


def candidate(kind, ident, evidence='public_ip'):
    return {'type': kind, 'id': ident, 'name': f'{kind}-{ident}',
        'evidence': [{'type': evidence, 'address': '192.168.0.3' if evidence == 'private_ip_unmapped' else '8.8.8.8'}],
        'object_type_conflict': kind == 'vm'}


def row(candidates, kind='dedicated_resource'):
    return {'kind': kind, 'match_status': 'CONFLICT', 'candidates': candidates}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.nb = {'datasets': {'devices': [{'id': 1, 'name': 'host-1'}, {'id': 2, 'name': 'host-2'}],
            'vms': [{'id': 3, 'name': 'gateway', 'device': {'id': 1}},
                    {'id': 4, 'name': 'other', 'device': {'id': 2}}]}}

    def test_same_host_and_gateway_are_one_proposal_not_adoption(self):
        result = contextual_review([row([candidate('device', 1), candidate('vm', 3)])], self.nb)[0]
        self.assertEqual(result['analysis_status'], 'TOPOLOGY_REVIEW_REQUIRED')
        self.assertEqual([c['id'] for c in result['proposed_candidates']], [1])
        self.assertFalse(result['auto_apply'])

    def test_different_hosts_remain_conflict(self):
        result = contextual_review([row([candidate('device', 1), candidate('vm', 4)])], self.nb)[0]
        self.assertEqual(result['analysis_status'], 'CONFLICT')

    def test_missing_parent_is_not_a_new_host(self):
        self.nb['datasets']['vms'][0]['device'] = None
        result = contextual_review([row([candidate('vm', 3)])], self.nb)[0]
        self.assertEqual(result['analysis_status'], 'CONFLICT')
        self.assertFalse(result['proposed_candidates'])

    def test_private_ip_alone_is_not_identity(self):
        result = contextual_review([row([candidate('vm', 3, 'private_ip_unmapped')], 'cloud_vm')], self.nb)[0]
        self.assertEqual(result['analysis_status'], 'NETWORK_SCOPE_REQUIRED')
        self.assertFalse(result['proposed_candidates'])

    def test_two_provider_records_cannot_claim_one_host(self):
        rows = [row([candidate('device', 1)]), row([candidate('vm', 3)])]
        result = contextual_review(rows, self.nb)
        self.assertEqual([r['analysis_status'] for r in result], ['CONFLICT', 'CONFLICT'])

    def test_input_unchanged_and_partial_collection_preserved(self):
        rows = [row([candidate('device', 1)])]
        rows[0]['match_status'] = 'INCOMPLETE_NETBOX_READ'
        before = copy.deepcopy(rows)
        result = contextual_review(rows, self.nb)
        self.assertEqual(rows, before)
        self.assertEqual(result[0]['analysis_status'], 'INCOMPLETE_NETBOX_READ')


if __name__ == '__main__':
    unittest.main()
