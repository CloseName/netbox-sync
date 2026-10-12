"""Synthetic regressions for issues discovered during the first operator audit."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.selectel_audit import __main__ as cli
from tools.selectel_audit.client import read_collection, sanitize
from tools.selectel_audit.collector import Collector, Credentials, source_bindings, collect_netbox
from tools.selectel_audit.coverage import summarize, resource_counts
from tools.selectel_audit.report import write_report
from tools.selectel_audit.test_audit import FakeClient, sample


def endpoint(typ, url, region='r'):
    return {'type': typ, 'endpoints': [{'interface': 'public', 'region': region, 'url': url}]}


class RevisionTests(unittest.TestCase):
    def test_glance_service_root_next_keeps_proxy_prefix(self):
        c = FakeClient([{'images': [{'id': 'a'}], 'next': '/v2/images?marker=a&limit=200'},
                        {'images': [{'id': 'b'}]}])
        result = read_collection(c, 'https://r.selcloud.ru/image/v2/images', 't', 'images', 'glance')
        self.assertEqual(result[2], 'collected')
        self.assertEqual(len(result[0]), 2)
        self.assertEqual(c.calls[1][0], 'https://r.selcloud.ru/image/v2/images?marker=a&limit=200')

    def test_glance_rewrite_never_authorizes_another_host_or_collection(self):
        for href in ('//evil.test/v2/images', 'https://evil.test/v2/images', '/v2/images/../secrets',
                     '/v2/images%2f..%2fsecrets', '/v2/images#fragment', '/v2/secrets'):
            with self.subTest(href=href):
                c = FakeClient([{'images': [{'id': 'a'}], 'next': href}])
                result = read_collection(c, 'https://r.selcloud.ru/image/v2/images', 't', 'images', 'glance')
                self.assertEqual(result[2], 'PAGINATION_OUTSIDE_COLLECTION')
                self.assertEqual(len(c.calls), 1)

    def test_glance_exception_is_not_applied_to_other_services(self):
        c = FakeClient([{'images': [{'id': 'a'}], 'next': '/v2/images?marker=a'}])
        self.assertEqual(read_collection(c, 'https://r.selcloud.ru/image/v2/images', 't', 'images')[2],
                         'PAGINATION_OUTSIDE_COLLECTION')

    def test_volume_alias_and_legacy_do_not_repeat_v3(self):
        c = FakeClient([{'volumes': []}, {'snapshots': []}])
        audit = Collector(Credentials('123', token='t'), c)
        audit.collect_catalog('t', [endpoint('volumev2', 'https://r.selcloud.ru/volume/v2/p'),
            endpoint('volume', 'https://r.selcloud.ru/volume/v3/p'),
            endpoint('volumev3', 'https://r.selcloud.ru/volume/v3/p')], 'p')
        self.assertEqual(len(c.calls), 2)
        self.assertTrue(all('/v3/' in x[0] for x in c.calls))
        statuses = [x['status'] for x in audit.document['coverage']]
        self.assertIn('SKIPPED_LEGACY_API', statuses)
        self.assertIn('SKIPPED_DUPLICATE_ENDPOINT', statuses)

    def test_v2_is_kept_when_region_has_no_trusted_v3(self):
        c = FakeClient([{'volumes': []}, {'snapshots': []}])
        audit = Collector(Credentials('123', token='t'), c)
        audit.collect_catalog('t', [endpoint('volumev3', 'https://evil.test/volume/v3/p'),
            endpoint('volumev2', 'https://r.selcloud.ru/volume/v2/p')], 'p')
        self.assertEqual(len(c.calls), 2)
        self.assertTrue(all('/v2/' in x[0] for x in c.calls))

    def test_technical_catalog_entry_is_not_attempted_or_reported_as_network_error(self):
        c = FakeClient([])
        audit = Collector(Credentials('123', token='t'), c)
        audit.collect_catalog('t', [endpoint('status', 'wss://r.selcloud.ru/status')], 'p')
        self.assertFalse(c.calls)
        self.assertEqual(audit.document['coverage'][0]['status'], 'UNSUPPORTED_SERVICE')

    def test_denied_partial_unsupported_and_skipped_are_distinct(self):
        statuses = ['HTTP_403', 'UNSUPPORTED_SERVICE', 'SKIPPED_LEGACY_API', 'HTTP_404']
        rows = [dict(service='s', status=s, count=0) for s in statuses]
        rows.append(dict(service='image', status='PAGINATION_OUTSIDE_COLLECTION', count=200, pages=1))
        result = summarize(rows)
        self.assertEqual(result['categories'], {'access_denied': 1, 'unsupported': 1, 'skipped': 1, 'unavailable': 1, 'partial': 1})
        self.assertEqual(result['requires_attention'], 3)
        self.assertEqual(result['account_completeness'], 'not_proven')

    def test_bindings_are_projected_without_arbitrary_custom_fields(self):
        obj = {'custom_fields': {'sync_identities': [{'schema': 'v2', 'type': 'esxi', 'instance': 'source',
            'kind': 'host', 'external_id': 'id', 'password': 'fake-secret'}], 'password': 'fake-secret'}}
        result = source_bindings(obj)
        self.assertEqual(result['status'], 'exported')
        self.assertNotIn('fake-secret', json.dumps(sanitize(result)))
        self.assertEqual(result['identities'][0]['external_id'], 'id')
        self.assertEqual(source_bindings({})['status'], 'not_present_in_response')
        self.assertEqual(source_bindings({'custom_fields': {'sync_identities': 'bad'}})['status'], 'invalid_identities_shape')

    def test_netbox_collection_retains_identity_projection_after_redaction(self):
        item = {'id': 1, 'name': 'host', 'custom_fields': {'sync_identities': [{'type': 'esxi', 'external_id': '1'}]}}
        c = FakeClient([{'results': [item], 'count': 1, 'next': None} for _ in range(6)])
        with patch('tools.selectel_audit.collector.Client', return_value=c):
            result = collect_netbox('https://nb.test', 'secret', progress=lambda _: None)
        self.assertEqual(result['datasets']['devices'][0]['source_bindings']['identities'][0]['type'], 'esxi')
        self.assertNotIn('custom_fields', json.dumps(result))

    def test_owned_networks_not_combined_with_external_and_containers_not_called_buckets(self):
        counts = resource_counts({'datasets': [
            dict(service='network', kind='networks', project='p', items=[{'project_id': 'p'}, {'project_id': 'provider'}]),
            dict(service='object-store', kind='buckets', items=[{'name': 'user'}, {'name': 'user_s3multipartuploads'}]) ]})
        self.assertEqual(counts['networks_project_owned_observations'], 1)
        self.assertEqual(counts['networks_other_or_unknown_owner_observations'], 1)
        self.assertEqual(counts['swift_multipart_suffix_observations'], 1)

    def test_report_preserves_failed_netbox_request_instead_of_not_requested(self):
        doc = sample()
        doc['netbox_read'] = {'requested': True, 'status': 'failed', 'error': 'TLS_CERTIFICATE_FAILED'}
        with tempfile.TemporaryDirectory() as temp:
            write_report(doc, Path(temp)/'report')
            result = json.loads((Path(temp)/'report/summary.json').read_text(encoding='utf-8'))
            self.assertEqual(result['netbox_coverage'], 'failed')
            self.assertTrue(result['netbox_read']['requested'])

    def test_unrecognized_answer_is_reprompted_and_token_is_required(self):
        with tempfile.TemporaryDirectory() as temp, patch('sys.argv', ['audit', '--output', temp]), \
            patch('builtins.input', side_effect=['123', '1', 'unrecognized', 'yes']), \
            patch.object(cli, 'hidden', side_effect=['provider-token', 'netbox-token']) as hidden, \
            patch.object(cli, 'Collector') as collector, patch.object(cli, 'collect_netbox') as netbox, \
            patch.object(cli, 'write_report', return_value=[]), patch('builtins.print'):
            collector.return_value.run.return_value = sample()
            netbox.return_value = {'coverage': [{'kind': 'devices', 'status': 'collected'}]}
            cli.main()
            self.assertEqual(hidden.call_count, 2)
            netbox.assert_called_once()


if __name__ == '__main__':
    unittest.main()
