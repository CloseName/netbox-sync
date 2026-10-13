"""Hidden resources must never look absent or ready for automatic adoption."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from .account import account_overview
from .report import account_html, write_report
from .test_audit import sample


def row(service, kind, count=0, status='collected', project='', region=''):
    return dict(service=service, kind=kind, count=count, status=status, project=project, region=region)


def document(coverage=(), projects=('p',), profile='all'):
    return dict(account='123', account_verified=True, profile=profile,
                projects=[{'id': p, 'name': p} for p in projects], coverage=list(coverage))


def product(doc, key):
    return next(p for p in account_overview(doc)['products'] if p['product'] == key)


class AccountTests(unittest.TestCase):
    def test_project_catalog_aliases_do_not_contaminate_account_collection(self):
        rows = [row('iam', 'projects', 2), row('resell', 'projects', 2),
                row('resell', 'floatingips', 3), row('resell', 'subnets', 1)]
        rows += [row(service, 'catalog', status='UNSUPPORTED_SERVICE', project='p', region='r')
                 for service in ('iam', 'resell')]
        doc = document(rows)
        self.assertEqual(product(doc, 'projects')['state'], 'collected')
        self.assertEqual(product(doc, 'cloud-allocation')['state'], 'collected')
        self.assertEqual(len(doc['coverage']), 6)
        rows[0]['status'] = 'HTTP_403'
        rows[0]['count'] = 0
        self.assertEqual(product(doc, 'projects')['state'], 'access_denied')

    def test_successful_zone_list_does_not_promise_record_support(self):
        result = product(document([row('selectel-dns', 'zones', 2, project='p')]), 'dns')
        self.assertEqual(result['state'], 'partial')
        self.assertEqual(result['adapter'], 'partial')
        self.assertIn('rrsets', str(result['scopes']))
        self.assertFalse(result['auto_apply'])

    def test_empty_denied_missing_and_unsupported_are_different(self):
        cases = [(document([row('selectel-dns', 'zones', project='p'), row('selectel-dns', 'rrsets', project='p')]), 'dns', 'empty'),
                 (document([row('selectel-dns', 'zones', status='HTTP_403', project='p'), row('selectel-dns', 'rrsets', status='HTTP_403', project='p')]), 'dns', 'access_denied'),
                 (document(), 'dns', 'not_checked'), (document(), 'managed-kubernetes', 'unsupported')]
        for doc, key, state in cases:
            self.assertEqual(product(doc, key)['state'], state)
            self.assertEqual(account_overview(doc)['account_completeness'], 'not_proven')

    def test_partial_pagination_keeps_counts_without_reporting_full_success(self):
        result = product(document([row('selectel-dns', 'zones', 100, 'HTTP_403', 'p')]), 'dns')
        self.assertEqual(result['state'], 'partial')
        self.assertEqual(result['observations_by_collection'], {'zones': 100})
        self.assertEqual(result['scopes'][0]['sections'][0]['code'], 'HTTP_403')

    def test_project_auth_failure_is_not_hidden_by_success_elsewhere(self):
        doc = document([row('selectel-dns', 'zones', 1, project='ok'),
                        row('identity', 'project_auth', status='HTTP_403', project='denied')],
                       projects=('ok', 'denied'))
        result = product(doc, 'dns')
        self.assertEqual(result['state'], 'partial')
        scopes = {s['project']: s for s in result['scopes']}
        self.assertEqual(scopes['denied']['state'], 'access_denied')
        self.assertEqual(scopes['ok']['observations_by_collection'], {'zones': 1})

    def test_success_and_empty_scopes_are_not_partial_failure(self):
        doc = document([row('selectel-dns', 'zones', 1, project='a'),
                        row('selectel-dns', 'zones', 0, project='b'),
                        row('selectel-dns', 'rrsets', 1, project='a'),
                        row('selectel-dns', 'rrsets', 0, project='b')], projects=('a', 'b'))
        self.assertEqual(product(doc, 'dns')['state'], 'collected')

    def test_expired_auth_and_no_projects_are_not_empty_resources(self):
        doc = document([row('identity', 'project_auth', status='HTTP_401', project='p')])
        self.assertEqual(product(doc, 's3')['state'], 'authentication_failed')
        self.assertEqual(product(document(projects=()), 's3')['state'], 'no_project_scope')

    def test_missing_expected_collection_prevents_success(self):
        doc = document([row('compute', 'servers', 1, project='p', region='r')])
        result = product(doc, 'compute')
        self.assertEqual(result['state'], 'partial')
        self.assertIn({'kind': 'flavors', 'code': 'NOT_CHECKED', 'state': 'not_checked', 'observations': 0},
                      result['scopes'][0]['sections'])

    def test_regions_are_independent_and_counts_are_not_global_total(self):
        rows = [row('compute', kind, 1, project='p', region='r1') for kind in ('servers', 'flavors')]
        rows += [row('compute', 'servers', status='HTTP_403', project='p', region='r2')]
        doc = document(rows)
        result = product(doc, 'compute')
        self.assertEqual(result['state'], 'partial')
        self.assertEqual(result['observations_by_collection'], {'servers': 1})
        self.assertNotIn('resource_count', account_overview(doc))

    def test_profiles_exclude_unqueried_products(self):
        doc = document(profile='servers')
        self.assertEqual(product(doc, 's3')['state'], 'excluded')
        self.assertEqual(product(doc, 'managed-databases')['state'], 'excluded')
        self.assertEqual(product(doc, 'compute')['state'], 'not_checked')
        self.assertEqual(product(doc, 'global-router')['state'], 'not_checked')

    def test_catalog_absence_and_skipped_aliases(self):
        doc = document([row('object-store', 'catalog', status='NOT_IN_CATALOG', project='p'),
            row('dnsv2', 'catalog', status='DELEGATED_TO_PROJECT_ADAPTER', project='p', region='r'),
            row('selectel-dns', 'zones', 2, project='p'),
            row('selectel-dns', 'rrsets', 3, project='p'),
            row('volumev2', 'catalog', status='SKIPPED_LEGACY_API', project='p', region='r'),
            row('volumev3', 'volumes', project='p', region='r'),
            row('volumev3', 'snapshots', project='p', region='r')])
        self.assertEqual(product(doc, 's3')['state'], 'not_in_catalog')
        self.assertEqual(product(doc, 'dns')['state'], 'collected')
        self.assertEqual(len(product(doc, 'dns')['scopes']), 1)
        self.assertEqual(product(doc, 'volumes')['state'], 'empty')

    def test_unknown_catalog_is_reported_not_inferred_as_resources_and_html_is_escaped(self):
        doc = document([row('<script>new-service</script>', 'catalog', status='UNSUPPORTED_SERVICE', project='p')])
        self.assertEqual(account_overview(doc)['unmapped_catalog_services'], ['<script>new-service</script>'])
        rendered = account_html(doc)
        self.assertNotIn('<script>new-service</script>', rendered)
        self.assertIn('&lt;script&gt;', rendered)

    def test_metadata_projection_does_not_copy_payloads_or_mutate_input(self):
        doc = document([row('selectel-dns', 'zones', 1, project='p')])
        doc['coverage'][0]['endpoint'] = 'https://example.invalid/?token=do-not-copy'
        doc['datasets'] = [{'items': [{'password': 'do-not-copy'}]}]
        before = copy.deepcopy(doc)
        result = account_overview(doc)
        self.assertNotIn('do-not-copy', json.dumps(result))
        self.assertEqual(doc, before)
        self.assertFalse(result['writes_performed'])

    def test_export_matches_html_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'report'
            write_report(sample(), path)
            overview = json.loads((path / 'account.json').read_text(encoding='utf-8'))
            summary = json.loads((path / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['account_overview']['states'], overview['states'])
            self.assertEqual(len(overview['products']), 20)
            text = (path / 'report.html').read_text(encoding='utf-8')
            for p in overview['products']:
                self.assertIn(p['title'], text)


if __name__ == '__main__':
    unittest.main()
