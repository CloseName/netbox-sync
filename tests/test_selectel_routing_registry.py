"""Global Router survives the actual audit -> Guard contract without inferred links."""
import copy
import importlib.util
from pathlib import Path
import pytest
from tools.selectel_audit.resource_registry import registry


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'deploy/netbox_guard' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = load('resource_registry_policy')
presentation = load('routing_presentation')


def document(account='123'):
    datasets = []
    for section, rows in (
        ('routers', [dict(id='r1', name='Router', account_id=account, project_id='p')]),
        ('networks', [dict(id='n1', router_id='r1', vlan=100, zone_id='z1')]),
        ('subnets', [dict(id='s1', network_id='n1', cidr='10.0.0.0/24', gateway='10.0.0.1')]),
        ('static_routes', [dict(id='route1', router_id='r1', subnet_id='s1', cidr='10.1.0.0/24', next_hop='10.0.0.2')]),
        ('zones', [dict(id='z1', visible_name='SPB', service='dedicated')]),
    ):
        datasets.append(dict(service='global-router', kind=section, status='collected', items=rows))
    return dict(account=account, finished_at='2026-11-04T10:00:00Z', datasets=datasets,
                coverage=[dict(service=d['service'], kind=d['kind'], status=d['status']) for d in datasets])


def test_topology_scope_allowlist_and_partial_retention():
    source = document()
    source['datasets'][0]['items'][0]['password'] = 'never-export'
    incoming = policy.normalize(registry(source))
    assert 'never-export' not in repr(incoming)
    first = policy.merge(None, incoming)
    router = next(r for r in first['resources'].values() if r['kind'] == 'global_router')
    children = presentation.components(router, list(first['resources'].values()), first['relations'].values())
    assert {r['kind'] for r in children} == {'routing_network', 'routing_subnet', 'routing_route'}
    network = next(r for r in children if r['kind'] == 'routing_network')
    assert ('Сервис', 'dedicated') in presentation.fields(network)
    assert set(first['resources']).isdisjoint(policy.normalize(registry(document('456')))['resources'])
    source['datasets'][1].update(status='HTTP_403', items=[])
    source['coverage'][1]['status'] = 'HTTP_403'
    second = policy.merge(first, policy.normalize(registry(source)))
    assert not second['resources'][network['key']]['present_in_latest']
    assert next(c for c in presentation.coverage(second) if c['label'] == 'Сети')['status'] == 'HTTP_403'


def test_unrelated_subnet_and_forged_relation_do_not_join_router():
    source = document()
    source['datasets'][2]['items'][0]['network_id'] = 'not-observed'
    normalized = policy.normalize(registry(source))
    subnet = next(r for r in normalized['resources'].values() if r['kind'] == 'routing_subnet')
    assert not any(e['target'] == subnet['key'] for e in normalized['relations'].values())
    forged = registry(document())
    edge = next(e for e in forged['relations'] if 'routing_subnet' in e['target'])
    edge['source'] = next(r['key'] for r in forged['resources'] if r['kind'] == 'global_router')
    with pytest.raises(ValueError):
        policy.normalize(forged)


def test_absent_coverage_is_not_empty_success():
    assert all(c['status'] == 'NOT_REPORTED' for c in presentation.coverage({}))
