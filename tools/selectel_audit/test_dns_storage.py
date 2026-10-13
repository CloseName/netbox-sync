"""Offline provider contracts; no credentials, infrastructure or network needed."""
import json
import unittest

from .client import AuditError, validate_url
from .collector import Collector, Credentials
from .dns_storage import collect_dns, collect_storage_details, container_path, export, storage_endpoint
from .test_audit import FakeClient


def catalog(kind='storage', region='ru-3', url='https://api.ru-3.storage.selcloud.ru'):
    return [{'type': kind, 'endpoints': [{'interface': 'public', 'region': region, 'url': url}]}]


def collector(responses):
    return Collector(Credentials('123', token='hidden-secret'), FakeClient(responses), progress=lambda _: None)


def buckets(c, project='p', status='collected', names=('bucket',)):
    c.document['datasets'].append(dict(service='object-store', kind='buckets', project=project,
        region='ru-3', status=status, items=[{'name': n} for n in names]))


class DNSStorageTests(unittest.TestCase):
    def test_dns_pages_and_allowlist(self):
        c = collector([{'result': [{'id': 'z', 'name': 'example.org', 'password': 'discard'}]},
            {'result': [{'id': 'r1', 'type': 'A', 'records': [{'content': '192.0.2.1',
              'comment': 'discard'}], 'comment': 'discard'}], 'next_offset': 1},
            {'result': [{'id': 'r2', 'type': 'TXT', 'records': [{'content': 'verification'}]}]}])
        collect_dns(c, 'hidden-secret', 'p')
        data = c.document['datasets'][-1]
        self.assertEqual(len(data['items']), 2)
        self.assertEqual(data['resource_id'], 'z')
        self.assertEqual(data['status'], 'collected')
        self.assertNotIn('discard', json.dumps(export(c.document)))
        self.assertIn('offset=1', c.client.calls[-1][0])
        self.assertTrue(all(not call[2] for call in c.client.calls))

    def test_dns_child_denied_retains_zone(self):
        c = collector([{'result': [{'id': 'z'}]}, AuditError('HTTP_403')])
        collect_dns(c, 't', 'p')
        self.assertEqual(c.document['datasets'][0]['items'], [{'id': 'z'}])
        self.assertEqual(c.document['datasets'][1]['status'], 'HTTP_403')

    def test_dns_invalid_ids_never_become_urls(self):
        c = collector([{'result': [{'id': '../objects'}]}])
        collect_dns(c, 't', 'p')
        self.assertEqual(len(c.client.calls), 1)
        self.assertEqual(c.document['datasets'][0]['status'], 'INVALID_RESOURCE_ID')

    def test_wrong_zone_record_not_saved(self):
        c = collector([{'result': [{'id': 'z'}]},
            {'result': [{'id': 'r', 'zone_id': 'other', 'records': []}]}])
        collect_dns(c, 't', 'p')
        self.assertEqual(c.document['datasets'][-1]['items'], [])
        self.assertEqual(c.document['datasets'][-1]['status'], 'DNS_ZONE_ID_MISMATCH')

    def test_storage_only_options_and_domains_not_objects(self):
        c = collector([{'general': {'type': 'private', 'secret': 'discard'},
                        'quota': {'max_object_count': 10}, 'web': {'listing_enabled': False},
                        'metadata': 'discard'}, {'domains': ['example.org'], 'cert': 'discard'}])
        buckets(c)
        collect_storage_details(c, 't', catalog(), 'p')
        self.assertEqual([call[0] for call in c.client.calls], [
            'https://api.ru-3.storage.selcloud.ru/v2/containers/bucket/options',
            'https://api.ru-3.storage.selcloud.ru/v2/containers/bucket/domains'])
        self.assertNotIn('discard', json.dumps(export(c.document)))
        self.assertTrue(all(not call[2] for call in c.client.calls))

    def test_storage_same_name_separate_projects(self):
        c = collector([{'general': {'type': 'private'}}, {'domains': []}] * 2)
        buckets(c, 'p'); buckets(c, 'q')
        collect_storage_details(c, 'token-p', catalog(), 'p')
        collect_storage_details(c, 'token-q', catalog(), 'q')
        self.assertEqual([call[1] for call in c.client.calls], ['token-p'] * 2 + ['token-q'] * 2)
        self.assertEqual({d['project'] for d in c.document['datasets'] if d['service'] == 'storage'}, {'p', 'q'})

    def test_storage_denied_and_malformed_are_not_empty(self):
        c = collector([AuditError('HTTP_403'), {'domains': [123]}])
        buckets(c)
        collect_storage_details(c, 't', catalog(), 'p')
        self.assertEqual([d['status'] for d in c.document['datasets'][1:]], ['HTTP_403', 'UNEXPECTED_FIELD_TYPE'])

    def test_empty_or_denied_parent_does_not_request_details(self):
        for status in ('collected', 'HTTP_403'):
            c = collector([])
            buckets(c, status=status, names=())
            collect_storage_details(c, 't', catalog(), 'p')
            self.assertFalse(c.client.calls)
            self.assertEqual({d['status'] for d in c.document['datasets']}, {status})

    def test_unmatched_region_or_ambiguous_catalog_no_requests(self):
        for cat, error in [(catalog(region='other'), 'STORAGE_ENDPOINT_NOT_IN_CATALOG'),
                (catalog() + catalog(url='https://api.ru-1.storage.selcloud.ru'), 'AMBIGUOUS_STORAGE_ENDPOINT'),
                (catalog(url='https://evil.invalid'), 'UNTRUSTED_OR_INVALID_ENDPOINT')]:
            c = collector([]); buckets(c)
            collect_storage_details(c, 't', cat, 'p')
            self.assertFalse(c.client.calls)
            self.assertEqual(c.document['datasets'][-1]['status'], error)

    def test_container_paths_and_management_paths_cannot_escape(self):
        for name in ('../secret', '.', '..', 'x/y', 'x%2Fy', 'x?y', 'x#y', 'x\\y'):
            with self.assertRaises(AuditError):
                container_path(name)
        with self.assertRaises(AuditError):
            storage_endpoint(catalog(url='https://api.ru-3.storage.selcloud.ru/other'), 'ru-3')

    def test_swift_account_path_guard_and_no_raw_fields(self):
        c = collector([])
        c.collect_catalog('t', catalog('object-store', url='https://swift.ru-3.storage.selcloud.ru/v1/other'), 'p')
        self.assertFalse(c.client.calls)
        self.assertIn('STORAGE_ACCOUNT_PATH_MISMATCH', str(c.document['coverage']))
        c = collector([[{'name': 'data_s3multipartuploads', 'bytes': 0, 'count': 0, 'metadata': 'discard'}]])
        c.collect_catalog('t', catalog('object-store', url='https://swift.ru-3.storage.selcloud.ru/v1/p'), 'p')
        self.assertTrue(c.document['datasets'][0]['items'][0]['multipart_name_hint'])
        self.assertNotIn('discard', json.dumps(c.document))

    def test_only_exact_documented_extra_hosts(self):
        for host in ('swift.uz-2.srvstorage.uz', 'api.uz-2.srvstorage.uz', 'swift.kz-1.srvstorage.kz'):
            validate_url('https://' + host)
            with self.assertRaises(AuditError):
                validate_url('https://' + host + '.evil.invalid')
        for host in ('api.kz-1.srvstorage.kz', 'swift.ru-3.pcs-3.storage.selprivate.ru'):
            with self.assertRaises(AuditError):
                validate_url('https://' + host)
