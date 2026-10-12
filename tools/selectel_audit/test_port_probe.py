import json
import unittest
from uuid import UUID

from .client import AuditError, IDENTITY
from .collector import Credentials, DEDICATED
from .port_probe import PortProbe, summarize


def uid(number):
    return str(UUID(int=number))


class Routes:
    def __init__(self, resources=(), routes=None, account='12345'):
        self.routes = {
            IDENTITY + '/auth/tokens': {'token': {'domain': {'name': account, 'id': uid(900)}}},
            DEDICATED + '/resource?limit=200&page=1': {'result': list(resources)},
        }
        self.routes.update({DEDICATED + k: v for k, v in (routes or {}).items()})
        self.calls = []

    def request(self, url, token='', **kwargs):
        if kwargs.get('payload') is not None:
            raise AssertionError('Probe attempted a write')
        self.calls.append(url)
        value = self.routes.get(url, AuditError('HTTP_404'))
        if isinstance(value, Exception):
            raise value
        return value, ''


class PortProbeTests(unittest.TestCase):
    def run_probe(self, client):
        return PortProbe(Credentials('12345', token='synthetic-secret-token'), client,
                         progress=lambda _: None).run()

    def test_account_mismatch_stops_before_provider_requests(self):
        client = Routes(account='54321')
        with self.assertRaisesRegex(AuditError, 'ACCOUNT_SCOPE_MISMATCH'):
            self.run_probe(client)
        self.assertEqual(client.calls, [IDENTITY + '/auth/tokens'])

    def test_discovery_uses_resource_hardware_and_port_ids_without_host_rules(self):
        resource = {'uuid': uid(1), 'hw_uuid': uid(2), 'service_type': 'custom'}
        port = {'uuid': uid(3), 'hw_uuid': uid(2), 'port_name': 'GE1/0/4',
                'is_enabled': False, 'is_aggregate': True, 'aggregate_physical_port_count': 2,
                'aux_network_info': {'mac_address': '00:11:22:33:44:55',
                                     'peer_name': 'synthetic-secret-token', 'password': 'private'}}
        second = dict(port, uuid=uid(4))
        routes = {
            '/resource/' + uid(1): {'result': resource},
            '/resource/' + uid(1) + '/aux_network_info': {'result': {'uuid': uid(1), 'ports': [port]}},
            '/network/port/hw/' + uid(2): {'result': [port, second]},
            '/network/port/' + uid(3): {'result': port},
            '/network/port/' + uid(4): {'result': second},
            '/network/port/' + uid(3) + '/network': {'result': []},
            '/network/port/' + uid(4) + '/network': {'result': []},
        }
        client = Routes([resource, {'uuid': uid(99), 'service_type': 'unrelated'}], routes)
        doc = self.run_probe(client)
        self.assertEqual(len(doc['resources']), 1)
        self.assertEqual(len(doc['records']), 7)
        self.assertFalse(doc['provider_port_confirmed'])
        self.assertFalse(doc['writes_performed'])
        self.assertFalse(doc['records'][1]['data']['ports'][0]['is_enabled'])
        self.assertTrue(doc['records'][1]['data']['ports'][0]['is_aggregate'])
        encoded = json.dumps(doc)
        self.assertNotIn('synthetic-secret-token', encoded)
        self.assertNotIn('password', encoded)
        self.assertNotIn('private', encoded)
        self.assertEqual(len(summarize(doc)['auxiliary_evidence']), 5)
        self.assertFalse(any(uid(99) in x for x in client.calls))

    def test_denied_missing_pending_and_empty_are_distinct(self):
        client = Routes(routes={'/empty': {'result': []}, '/denied': AuditError('HTTP_403'),
                                '/pending': AuditError('ASYNC_RESPONSE_NOT_COLLECTED')})
        probe = PortProbe(Credentials('12345', token='t'), client)
        statuses = [probe.get(path, 'ports')['status'] for path in
                    ('/empty', '/denied', '/missing', '/pending')]
        self.assertEqual(statuses, ['empty', 'denied', 'not_found', 'pending'])

    def test_partial_resource_enumeration_is_not_reported_as_success(self):
        client = Routes()
        client.routes[DEDICATED + '/resource?limit=200&page=1'] = {
            'result': [{'uuid': uid(1), 'service_type': 'custom'}], 'limit': 1}
        doc = self.run_probe(client)
        self.assertEqual(doc['resource_enumeration']['code'], 'HTTP_404')
        self.assertEqual(len(doc['resources']), 1)
        self.assertIn('HARDWARE_UUID_NOT_REPORTED:' + uid(1), doc['notes'])

    def test_hardware_queries_are_cached_and_conflicting_resource_is_reported(self):
        resources = [{'uuid': uid(i), 'hw_uuid': uid(9), 'service_type': 'server'} for i in (1, 2)]
        routes = {'/resource/' + uid(1): {'result': {'uuid': uid(99), 'hw_uuid': uid(10)}}}
        client = Routes(resources, routes)
        doc = self.run_probe(client)
        self.assertEqual(client.calls.count(DEDICATED + '/network/port/hw/' + uid(9)), 1)
        self.assertNotIn(DEDICATED + '/network/port/hw/' + uid(10), client.calls)
        self.assertIn('RESOURCE_RESPONSE_ID_MISMATCH:' + uid(1), doc['notes'])

    def test_auxiliary_shape_and_pagination_are_explicit(self):
        client = Routes(routes={'/aux': {'result': {'uuid': uid(1), 'ports': None}},
                                '/ports': {'result': [{'uuid': uid(2)}], 'total': 2}})
        probe = PortProbe(Credentials('12345', token='t'), client)
        self.assertEqual(probe.get('/aux', 'auxiliary')['code'], 'PORTS_FIELD_MISSING_OR_INVALID')
        partial = probe.get('/ports', 'ports')
        self.assertEqual(partial['code'], 'PAGINATION_UNRESOLVED')
        self.assertEqual(len(partial['data']), 1)

    def test_exhausted_budget_preserves_partial_report(self):
        client = Routes([{'uuid': uid(i), 'service_type': 'custom'} for i in range(1, 4)],
                        {'/resource/' + uid(1): AuditError('REQUEST_BUDGET_EXCEEDED')})
        doc = self.run_probe(client)
        self.assertIn('PROBE_STOPPED_EARLY', doc['notes'])
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(doc['records'][0]['code'], 'REQUEST_BUDGET_EXCEEDED')

    def test_auxiliary_resource_mismatch_does_not_expand_wrong_ports(self):
        client = Routes([{'uuid': uid(1), 'service_type': 'custom'}], {
            '/resource/' + uid(1) + '/aux_network_info': {
                'result': {'uuid': uid(2), 'ports': [{'uuid': uid(3)}]}}})
        doc = self.run_probe(client)
        self.assertIn('AUX_RESPONSE_ID_MISMATCH:' + uid(1), doc['notes'])
        self.assertNotIn(DEDICATED + '/network/port/' + uid(3), client.calls)


if __name__ == '__main__':
    unittest.main()
