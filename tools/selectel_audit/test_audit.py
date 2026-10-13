"""Offline tests: no provider, NetBox or credential access."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.selectel_audit.client import (AuditError, Client, IDENTITY, NoRedirect,
    read_collection, sanitize, validate_url, field_shapes)
from tools.selectel_audit.collector import Credentials, Collector, child_url
from tools.selectel_audit.report import write_report
from tools.selectel_audit.review import inventory, match_candidates


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.requests = 0

    def request(self, url, token='', **kwargs):
        self.calls.append((url, token, kwargs))
        self.requests += 1
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, tuple) else (value, '')


class ReaderTests(unittest.TestCase):
    def test_untrusted_endpoints(self):
        for url in ('http://api.selectel.ru/x', 'https://selectel.ru.attacker.invalid/x',
                    'https://localhost/x', 'https://api.selectel.ru:8443/x',
                    'https://user:secret@api.selectel.ru/x', 'https://api.selectel.ru/x#token'):
            with self.subTest(url=url), self.assertRaises(AuditError):
                validate_url(url)

    def test_forbidden_write_never_reaches_transport(self):
        client = Client()
        with patch.object(client.opener, 'open') as opened:
            with self.assertRaisesRegex(AuditError, 'WRITE_REFUSED'):
                client.request('https://api.selectel.ru/servers/v2/resource', payload={})
            opened.assert_not_called()

    def test_netbox_cannot_receive_selectel_auth_or_follow_another_origin(self):
        client = Client(netbox_origin=('https', 'nb.test'))
        with self.assertRaises(AuditError):
            client.request(IDENTITY + '/auth/tokens', payload={})
        with self.assertRaises(AuditError):
            client.request('https://nb.test/login/')

    def test_redirect_refused(self):
        with self.assertRaisesRegex(AuditError, 'REDIRECT_REFUSED'):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test')

    def test_cross_origin_next_retains_first_page_and_marks_partial(self):
        client = FakeClient([{'servers': [{'id': '1'}],
            'servers_links': [{'rel': 'next', 'href': 'https://evil.test/servers'}]}])
        items, _, status = read_collection(client, 'https://api.selectel.ru/servers', 'secret', 'servers')
        self.assertEqual(len(items), 1)
        self.assertEqual(status, 'PAGINATION_OUTSIDE_COLLECTION')
        self.assertEqual(len(client.calls), 1)

    def test_same_origin_different_path_next_refused(self):
        client = FakeClient([{'servers': [{'id': '1'}], 'next': '/password'}])
        self.assertEqual(read_collection(client, 'https://api.selectel.ru/servers', '', 'servers')[2],
                         'PAGINATION_OUTSIDE_COLLECTION')

    def test_server_pagination_and_partial_failure(self):
        client = FakeClient([{'servers': [{'id': '1'}], 'links': {'next': '?marker=1'}},
                             AuditError('HTTP_403')])
        items, pages, status = read_collection(client, 'https://api.selectel.ru/servers', '', 'servers')
        self.assertEqual((len(items), len(pages), status), (1, 1, 'HTTP_403'))

    def test_dedicated_honors_server_page_limit(self):
        client = FakeClient([{'result': [{'uuid': 'a'}], 'limit': 1}, {'result': [], 'limit': 1}])
        items, _, status = read_collection(client, 'https://api.selectel.ru/resource', '', 'result', 'page')
        self.assertEqual((len(items), status), (1, 'collected'))
        self.assertIn('page=2', client.calls[-1][0])

    def test_page_loop_is_not_success(self):
        data = {'result': [{'uuid': 'a'}], 'limit': 1}
        client = FakeClient([data, data])
        self.assertEqual(read_collection(client, 'https://api.selectel.ru/resource', '', 'result', 'page')[2],
                         'PAGINATION_REPEATED_PAGE')

    def test_unexpected_shape_is_preserved_for_schema_review(self):
        client = FakeClient([{'result': {'new_api_shape': 1}}])
        items, pages, status = read_collection(client, 'https://api.selectel.ru/x', '', 'result')
        self.assertEqual(status, 'UNEXPECTED_RESPONSE_SHAPE')
        self.assertTrue(pages)
        self.assertFalse(items)

    def test_netbox_count_truncation(self):
        client = FakeClient([{'results': [{'id': 1}], 'count': 3, 'next': None}])
        self.assertEqual(read_collection(client, 'https://nb.test/api/dcim/devices/', '', 'results', 'netbox')[2],
                         'COUNT_MISMATCH')

    def test_dns_offset(self):
        client = FakeClient([{'result': [{'id': 'a'}], 'next_offset': 1},
                             {'result': [], 'next_offset': 1}])
        self.assertEqual(read_collection(client, 'https://api.selectel.ru/zones', '', 'result', 'offset')[2],
                         'collected')
        self.assertIn('offset=1', client.calls[-1][0])

    def test_versioned_catalog_path(self):
        self.assertEqual(child_url('https://x.selcloud.ru/network/v2.0/', 'v2.0/ports'),
                         'https://x.selcloud.ru/network/v2.0/ports')

    def test_single_endpoint_with_truncation_is_not_complete(self):
        client = FakeClient([{'result': [{'id': 'a'}], 'limit': 1}])
        self.assertEqual(read_collection(client, 'https://api.selectel.ru/x', '', 'result', 'single')[2],
                         'PAGINATION_UNRESOLVED')

    def test_application_error_is_not_empty_success(self):
        client = FakeClient([{'result': [], 'status': 'error'}])
        self.assertEqual(read_collection(client, 'https://api.selectel.ru/x', '', 'result')[2],
                         'PROVIDER_RESPONSE_ERROR')

    def test_sanitization_secrets_and_opaque_fields(self):
        raw = {'password': 'p', 'adminPass': 'p', 'metadata': {'x': 'p'}, 'user_data': 'p',
               'nested': [{'x': 'contains fake-secret', 'secret': 'p'}], 'addresses': ['10.0.0.1']}
        result = sanitize(raw, ['fake-secret'])
        self.assertNotIn('fake-secret', json.dumps(result))
        self.assertEqual(result['metadata'], '[REDACTED]')
        self.assertEqual(result['addresses'], ['10.0.0.1'])
        self.assertNotIn('$.metadata.x', field_shapes(raw))


class AuthTests(unittest.TestCase):
    def test_account_mismatch_stops_before_inventory(self):
        c = Credentials('123', token='t')
        with self.assertRaisesRegex(AuditError, 'ACCOUNT_SCOPE_MISMATCH'):
            c.authenticate(FakeClient([{'token': {'domain': {'id': 'd', 'name': '999'}}}]))

    def test_project_token_is_not_an_account_token(self):
        c = Credentials('123', token='t')
        with self.assertRaises(AuditError):
            c.authenticate(FakeClient([{'token': {'project': {'id': 'p', 'domain': {'name': '123'}}}}]))

    def test_rescope_validates_returned_project(self):
        c = Credentials('123', token='t')
        client = FakeClient([({'token': {'project': {'id': 'wrong', 'domain': {'id': 'd', 'name': '123'}}}}, 'new')])
        with self.assertRaisesRegex(AuditError, 'PROJECT_SCOPE_MISMATCH'):
            c.authenticate(client, 'wanted')

    def test_service_password_only_sent_to_identity(self):
        c = Credentials('123', username='audit', password='p')
        client = FakeClient([({'token': {'domain': {'id': 'd', 'name': '123'}}}, 't')])
        c.authenticate(client)
        self.assertEqual(client.calls[0][0], IDENTITY + '/auth/tokens')
        self.assertEqual(c.token, 't')


def sample():
    return {'account': '123', 'account_verified': True, 'projects': [{'id': 'p'}],
        'coverage': [], 'limitations': [], 'datasets': [
        {'service': 'compute', 'kind': 'servers', 'project': 'p', 'region': 'r',
         'status': 'collected', 'fields': {}, 'items': [
             {'id': 'vm-1', 'name': 'host.test', 'addresses': {'lan': [{'addr': '10.0.0.1'}]}}]}]}


def nb():
    return {'datasets': {'vms': [{'id': 1, 'name': 'host.test'}],
        'vm_interfaces': [{'id': 10, 'virtual_machine': {'id': 1}}],
        'ips': [{'id': 11, 'address': '10.0.0.1/24', 'vrf': {'id': 4},
                 'assigned_object_type': 'virtualization.vminterface', 'assigned_object_id': 10}]},
        'coverage': [{'kind': 'vms', 'status': 'collected'}]}


class MatchingTests(unittest.TestCase):
    def test_private_ip_and_name_never_auto_adopt(self):
        rows = match_candidates(inventory(sample()), nb())
        self.assertEqual(rows[0]['match_status'], 'REVIEW_REQUIRED')
        self.assertFalse(rows[0]['auto_apply'])
        self.assertIn('private_ip_unmapped', str(rows[0]['candidates']))

    def test_same_ip_on_two_objects_conflicts(self):
        data = nb()
        data['datasets']['vms'].append({'id': 2, 'name': 'other', 'primary_ip4': {'address': '10.0.0.1/24'}})
        self.assertEqual(match_candidates(inventory(sample()), data)[0]['match_status'], 'CONFLICT')

    def test_two_projects_cannot_claim_one_vm(self):
        doc = sample()
        second = copy.deepcopy(doc['datasets'][0]); second['project'] = 'other'
        doc['datasets'].append(second)
        rows = match_candidates(inventory(doc), nb())
        self.assertEqual([x['match_status'] for x in rows], ['CONFLICT', 'CONFLICT'])

    def test_wrong_object_type_conflict(self):
        data = nb(); data['datasets']['devices'] = data['datasets'].pop('vms')
        self.assertEqual(match_candidates(inventory(sample()), data)[0]['match_status'], 'CONFLICT')

    def test_failed_netbox_read_cannot_mean_new_object(self):
        data = nb(); data['coverage'][0]['status'] = 'HTTP_403'
        self.assertEqual(match_candidates(inventory(sample()), data)[0]['match_status'], 'INCOMPLETE_NETBOX_READ')

    def test_no_candidate_is_not_authorized_create(self):
        data = nb(); data['datasets'] = {}
        rows = match_candidates(inventory(sample()), data)
        self.assertEqual(rows[0]['match_status'], 'NO_CANDIDATE')
        self.assertFalse(rows[0]['auto_apply'])

    def test_offline_report_escapes_html_and_does_not_overwrite(self):
        doc = sample(); doc['datasets'][0]['items'][0]['name'] = '<script>alert(1)</script>'
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'report'
            write_report(doc, target)
            text = (target / 'report.html').read_text(encoding='utf8')
            self.assertNotIn('<script>alert(1)</script>', text)
            self.assertIn('&lt;script&gt;', text)
            self.assertEqual({p.name for p in target.iterdir()}, {
                'inventory.json', 'account.json', 'dns-storage.json', 'fields.json', 'summary.json', 'report.html', 'summary.txt'})
            with self.assertRaises(FileExistsError):
                write_report(doc, target)


class FullAuditTests(unittest.TestCase):
    def test_project_isolation_and_all_exports_exclude_credentials(self):
        class Provider:
            requests = 0
            def request(self, url, token='', **kwargs):
                self.requests += 1
                if url.endswith('/auth/tokens'):
                    payload = kwargs.get('payload')
                    if payload:
                        project = payload['auth']['scope']['project']['id']
                        if project == 'denied':
                            raise AuditError('HTTP_403')
                        return {'token': {'project': {'id': project, 'domain': {'id': 'd', 'name': '123'}},
                            'catalog': [{'type': 'compute', 'endpoints': [{'interface': 'public',
                                'region': 'ru-test', 'url': 'https://ru-test.cloud.api.selcloud.ru/compute/v2.1'}]}]}}, 'project-secret'
                    return {'token': {'domain': {'name': '123', 'id': 'd'}}}, ''
                if '/projects' in url:
                    return {'projects': [{'id': 'ok', 'name': 'Example'}, {'id': 'denied', 'name': 'Hidden'}]}, ''
                if '/resell/v2/floatingips' in url:
                    return {'floatingips': []}, ''
                if '/resell/v2/subnets' in url:
                    return {'subnets': []}, ''
                if 'servers/detail' in url:
                    return {'servers': [{'id': 'vm', 'name': 'example-vm', 'adminPass': 'must-hide',
                                          'metadata': {'k': 'must-hide'}}]}, ''
                if 'flavors/detail' in url:
                    return {'flavors': [{'id': 'flavor', 'ram': 2048, 'vcpus': 2}]}, ''
                if '/naas/' in url:
                    return [], ''
                if '/domains/v2/zones' in url:
                    return {'result': [], 'next_offset': 0, 'count': 0}, ''
                return {'result': [], 'limit': 200}, ''
        document = Collector(Credentials('123', token='account-secret'), client=Provider(),
                             progress=lambda _: None).run()
        self.assertEqual(len(document['projects']), 2)
        self.assertTrue(any(x['project'] == 'denied' and x['status'] == 'HTTP_403'
                            for x in document['coverage']))
        self.assertEqual(document['account_completeness'], 'not_proven')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'audit'
            rows = write_report(document, path)
            self.assertEqual(len(rows), 1)
            exported = '\n'.join(x.read_text(encoding='utf8') for x in path.iterdir())
            for secret in ('account-secret', 'project-secret', 'must-hide'):
                self.assertNotIn(secret, exported)


if __name__ == '__main__':
    unittest.main()
