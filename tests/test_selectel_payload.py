"""Production regression: duplicated audit responses filled a 24 MiB pipe file."""
import copy
import io
import json
import tempfile
from unittest.mock import patch

import pytest
from tests.test_selectel_inventory import mod
Inventory = mod.Inventory
from netbox_sync import selectel_collect as collect
from netbox_sync.selectel_payload import inventory_document, bounded_json, import_payload
from netbox_sync.selectel_runner import child_result
from tests.selectel_inventory_fixture import fixture
from tools.selectel_audit.resource_registry import registry


def catalog_fixture():
    document = fixture('29916')
    server = next(d for d in document['datasets'] if d['service'] == 'compute' and d['kind'] == 'servers')
    server['items'][0]['image'] = {'id': 'used-image'}
    document['datasets'].append(dict(service='image', kind='images', project='p', region='r',
        status='collected', items=[{'id': 'used-image', 'name': 'Chosen OS'}, {'id': 'unused', 'name': 'Unused'}]))
    flavors = next(d for d in document['datasets'] if d['kind'] == 'flavors')
    flavors['items'].append({'id': 'unused', 'name': 'Unused flavor'})
    return document


def test_catalogs_are_scoped_and_preserve_inventory_with_large_unused_catalogs():
    document = catalog_fixture()
    # Public catalogs repeated in many scopes are choices, not owned VMs/disks.
    for i in range(90):
        document['datasets'].append(dict(service='image', kind='images', project='p', region=f'region-{i}',
            status='collected', items=[{'id': 'used-image', 'name': 'Wrong scope', 'metadata': 'x'*300000}]))
    before = copy.deepcopy(document)
    compact = inventory_document(document)
    assert Inventory(compact).normalize() == Inventory(document).normalize()
    assert document == before
    assert len(bounded_json(compact)) < 100000
    images = [d for d in compact['datasets'] if d['kind'] == 'images']
    assert [row['name'] for d in images for row in d['items']] == ['Chosen OS']
    assert len(images) == 91  # Keep endpoint status even when no VM uses its entries.


@pytest.mark.parametrize('conflict', ['items', 'status', 'none'])
def test_catalog_filter_cannot_hide_conflicts(conflict):
    document = catalog_fixture()
    original = document['datasets'][-1]
    duplicate = copy.deepcopy(original)
    if conflict == 'items':
        duplicate['items'][-1]['name'] = 'Different unused row'
    if conflict == 'status':
        duplicate['status'] = 'HTTP_403'
    document['datasets'].append(duplicate)
    compact = inventory_document(document)
    assert Inventory(compact).normalize() == Inventory(document).normalize()
    assert len(compact['datasets'][-1]['items']) == (1 if conflict == 'none' else 2)


@pytest.mark.parametrize('status', ['collected', 'HTTP_403', 'NOT_COLLECTED'])
def test_missing_catalog_ids_and_partial_results_keep_old_join_semantics(status):
    document = catalog_fixture()
    server = next(d for d in document['datasets'] if d['kind'] == 'servers')['items'][0]
    server.pop('image')
    images = document['datasets'][-1]
    images['status'] = status
    images['items'].extend([{'name': 'Missing ID'}, {'id': None, 'name': 'Second missing ID'}])
    compact = inventory_document(document)
    assert Inventory(compact).normalize() == Inventory(document).normalize()
    assert compact['datasets'][-1]['status'] == status


def test_large_audit_preserves_server_inventory_registry_and_failures():
    document = fixture('29916')
    document['projects'] = [{'id': 'p', 'name': 'Project'}]
    document['coverage'] = [{'service': 'network', 'kind': 'routers', 'status': 'HTTP_403'}]
    document['datasets'].extend([
        dict(service='selectel-dns', kind='zones', project='p', status='collected', items=[{'id': 'z', 'name': 'example.test'}]),
        dict(service='object-store', kind='buckets', project='p', status='collected', items=[{'name': 'bucket'}]),
    ])
    document['datasets'][0]['responses'] = [{'raw': 'x' * (25 * 1024 * 1024)}]
    document['datasets'][0]['fields'] = {'raw': ['string']}
    before = copy.deepcopy(document)
    with patch.object(collect, 'Collector') as factory:
        factory.return_value.run.return_value = document
        result = collect.run(dict(operation='collect', account='29916', username='reader', password='SECRET'))
        assert factory.call_args.kwargs['progress']('not protocol data') is None
    assert Inventory(result['document']).normalize() == Inventory(document).normalize()
    assert result['registry'] == registry(document)
    assert result['summary'] == collect.summary(document)
    assert result['document']['coverage'] == document['coverage']
    assert document == before
    assert len(bounded_json(result)) < 100000
    assert 'responses' not in result['document']['datasets'][0]
    assert {r['kind'] for r in result['registry']['resources']} >= {'dns_zone', 'storage_container'}


def test_main_stdout_is_one_json_even_if_dependency_prints(capsys):
    def noisy(_):
        print('progress that is not JSON')
        return {'document': {}, 'registry': {}, 'summary': {}}
    with patch.object(collect.sys, 'stdin', io.StringIO('{"operation":"collect"}')), patch.object(collect, 'run', noisy):
        collect.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out)['document'] == {}
    assert 'progress' not in captured.out


def test_bounded_wire_matches_requests_encoding_including_unicode():
    value = {'name': 'Сервер', 'items': [1, None]}
    encoded = json.dumps(value, allow_nan=False).encode('utf-8')
    with patch('netbox_sync.selectel_payload.MAX_BYTES', len(encoded)):
        assert bounded_json(value) == encoded
    with patch('netbox_sync.selectel_payload.MAX_BYTES', len(encoded) - 1):
        with pytest.raises(ValueError, match='SELECTEL_RESULT_TOO_LARGE'):
            bounded_json(value)


def test_envelope_limit_checked_before_import_request():
    result = dict(document={}, registry={})
    with patch('netbox_sync.selectel_payload.MAX_BYTES', 10):
        with pytest.raises(ValueError, match='SELECTEL_RESULT_TOO_LARGE'):
            import_payload('29916', '0'*36, result)
        with patch('netbox_sync.retirement_transport.GuardClient') as guard, \
             patch('netbox_sync.netbox_tls.configure_session'), \
             patch('netbox_sync.netbox_auth.authorization', return_value='Bearer secret'):
            with pytest.raises(ValueError, match='SELECTEL_RESULT_TOO_LARGE'):
                collect.run(dict(operation='import', url='https://example.test', token='secret',
                                 guard_instance='unused', payload={'data': 'x'*100}))
            guard.return_value._request.assert_not_called()


def test_oversized_result_becomes_small_complete_error(capsys):
    with patch('netbox_sync.selectel_payload.MAX_BYTES', 128), \
         patch.object(collect.sys, 'stdin', io.StringIO('{"operation":"collect"}')), \
         patch.object(collect, 'run', return_value={'huge': 'x'*1024}):
        collect.main()
    assert json.loads(capsys.readouterr().out) == {'error': 'SELECTEL_RESULT_TOO_LARGE'}


@pytest.mark.parametrize('raw,code,expected', [
    (b'x'*1025, 120, 'SELECTEL_RESULT_TOO_LARGE'),
    (b'', 120, 'SELECTEL_COLLECTOR_EXITED'),
    (b'progress\n{}', 0, 'SELECTEL_RESULT_INVALID'),
    (b'[]', 0, 'SELECTEL_RESULT_INVALID'),
    (b'{}', 0, 'SELECTEL_RESULT_INVALID'),
])
def test_child_failures_are_distinct_and_import_remains_uncertain(raw, code, expected):
    with tempfile.TemporaryFile() as output, patch('netbox_sync.selectel_runner.MAX_BYTES', 1024):
        output.write(raw)
        output.flush()
        assert child_result(output, code, 'collect') == {'error': expected}
        if raw != b'{}':
            assert child_result(output, code, 'import') == {'error': 'IMPORT_UNCONFIRMED'}
