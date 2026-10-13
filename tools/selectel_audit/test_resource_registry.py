import copy
import unittest

from .resource_registry import registry, registry_html
from .coverage import summarize
from .account import account_overview
from .dns_storage import collect_storage_details
from .test_dns_storage import collector, buckets, catalog


def ds(kind, items, project='p', region='r', parent=None, status='collected'):
    return dict(service='selectel-dns' if kind in ('zones', 'rrsets') else
                'object-store' if kind == 'buckets' else 'storage',
                kind=kind, items=items, project=project, region=region,
                resource_id=parent, status=status)


class RegistryTests(unittest.TestCase):
    def test_scope_isolation_and_deterministic_identity(self):
        d = {'account': 'a', 'datasets': [ds('buckets', [{'name': 'same'}], project=p, region=r)
             for p, r in [('p', 'r'), ('q', 'r'), ('p', 's')]]}
        before = copy.deepcopy(d)
        a = registry(d)
        self.assertEqual(d, before)
        self.assertEqual(a['counts']['storage_container'], 3)
        self.assertEqual(len({n['key'] for n in a['resources']}), len(a['resources']))
        d['datasets'].reverse()
        self.assertEqual(a['resources'], registry(d)['resources'])
        self.assertEqual(a['relations'], registry(d)['relations'])
        d['account'] = 'b'
        self.assertTrue(set(n['key'] for n in a['resources']).isdisjoint(n['key'] for n in registry(d)['resources']))

    def test_missing_parent_is_unconfirmed_and_no_guessed_ip_links(self):
        d = {'account': 'a', 'datasets': [ds('rrsets', [{'id': 'rr', 'type': 'A',
            'records': [{'content': '192.0.2.1'}]}], parent='z')]}
        r = registry(d)
        self.assertEqual(r['unconfirmed_relations'][0]['code'], 'PARENT_NOT_OBSERVED')
        self.assertNotIn('dns_zone', r['counts'])
        self.assertFalse(any(e['relation'] != 'contains' for e in r['relations']))

    def test_domains_and_multipart_are_not_merged(self):
        d = {'account': 'a', 'datasets': [ds('buckets', [{'name': 'b'}, {'name': 'b_s3multipartuploads'}]),
            ds('container_domains', [{'domains': ['<example>']}], parent='b'),
            ds('container_options', [{'general': {'type': 'private'}}], parent='b')]}
        r = registry(d)
        self.assertEqual(r['counts']['storage_container'], 2)
        self.assertEqual(r['counts']['storage_domain'], 1)
        self.assertEqual(sum(e['relation'] == 'custom_domain' for e in r['relations']), 1)
        self.assertNotIn('<example>', registry_html(r))
        self.assertIn('&lt;example&gt;', registry_html(r))

    def test_duplicate_conflicts_retained_and_missing_not_deleted(self):
        d = {'account': 'a', 'datasets': [ds('buckets', [{'name': 'b', 'bytes': 1}, {'name': 'b', 'bytes': 2}])]}
        r = registry(d)
        n = next(n for n in r['resources'] if n['kind'] == 'storage_container')
        self.assertEqual(n['conflicting_sections'], ['buckets'])
        self.assertEqual(len(n['observations']), 2)
        self.assertTrue(r['snapshot_only'])
        self.assertFalse(r['writes_performed'])

    def test_parent_failure_counted_once(self):
        c = collector([])
        buckets(c, status='HTTP_403', names=())
        c.document['coverage'].append(dict(service='object-store', kind='buckets', project='p',
            region='ru-3', status='HTTP_403', count=0))
        c.document['projects'] = [{'id': 'p'}]
        collect_storage_details(c, 't', catalog(), 'p')
        counts = summarize(c.document['coverage'])['categories']
        self.assertEqual(counts, {'access_denied': 1, 'dependency_unavailable': 2})
        state = next(p for p in account_overview(c.document)['products'] if p['product'] == 's3')
        self.assertEqual(state['state'], 'access_denied')
        self.assertFalse(c.client.calls)
