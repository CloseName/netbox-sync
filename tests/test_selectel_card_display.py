"""Readable native cards retain provider facts without pretending IP ownership."""
import importlib
from pathlib import Path
import sys
from types import ModuleType


package = ModuleType('selectel_display_fixture')
package.__path__ = [str(Path(__file__).parents[1] / 'deploy/netbox_guard')]
sys.modules[package.__name__] = package


def test_native_card_components_and_addresses():
    panel = importlib.import_module(package.__name__ + '.provider_card_display').panel
    snapshot = dict(identity=dict(account='123', project='p', region='', kind='dedicated'), sections={
        'hardware': {'data': {'cpu': [{'name': 'Xeon', 'count': 2}],
                              'ram': [{'name': '32 GB ECC', 'count': 4}],
                              'disk': [{'name': 'SSD 960 GB', 'count': 2}]}},
        'public_ips': {'data': [{'ip': '94.26.228.220'}]},
        'private_ips': {'data': [{'ip': '10.25.0.1'}]},
        'placement': {'data': {'name': 'SPB-4'}},
    })
    value = panel(snapshot, 'Production')
    assert dict(value['fields'])['Процессоры'] == '2 × Xeon'
    assert dict(value['fields'])['Память'] == '4 × 32 GB ECC'
    assert value['addresses'] == ['94.26.228.220', '10.25.0.1']
    assert value['project'] == 'Production' and value['location'] == 'SPB-4'
    assert 'primary' not in value
    snapshot['identity']['kind'] = 'cloud_vm'
    snapshot['sections']['hardware']['data'] = {'vcpus': 8, 'ram': 16384}
    assert not panel(snapshot)['fields']  # VM resources already have native fields.
    assert panel(None) is None


def test_routing_search_subnet_membership_and_orphans():
    browser = importlib.import_module(package.__name__ + '.routing_browser')
    rows = [dict(key='r', kind='global_router', sections={'routers': {'data': {'name': 'Router'}}}),
            dict(key='n', kind='routing_network', sections={'networks': {'data': {'name': 'LAN', 'vlan': 1368}}}),
            dict(key='s', kind='routing_subnet', sections={'subnets': {'data': {'cidr': '10.78.12.0/26', 'gateway': '10.78.12.1'}}}),
            dict(key='orphan', kind='routing_network', sections={'networks': {'data': {'name': 'Unknown parent'}}})]
    edges = [dict(source='r', target='n', relation='contains'), dict(source='n', target='s', relation='contains')]
    result = browser.context(rows, edges, rows[0], '10.78.12.42', {})
    assert [n['name'] for n in result['networks']] == ['LAN']
    assert result['networks'][0]['subnets'][0]['broadcast'] == '10.78.12.63'
    assert browser.context(rows, edges, rows[0], '10.79.1.1', {})['networks'] == []
    assert browser.context(rows, edges, None, '', {})['unlinked'][0]['name'] == 'Unknown parent'
    assert result['routing_problems']


def test_unified_hardware_host_priority_and_physical_disks():
    hardware = importlib.import_module(package.__name__ + '.hardware_display').panel
    snapshot = dict(identity=dict(kind='dedicated'), sections={'hardware': {'data': {
        'cpu': [{'name': 'Provider CPU', 'count': 1}],
        'ram': [{'name': '32 GB ECC', 'count': 8}],
        'disk': [{'name': '6 TB HDD SATA Enterprise', 'count': 2},
                 {'name': '480 GB SSD SATA', 'count': 2},
                 {'name': '6 TB HDD SATA Enterprise', 'count': 2}]}}})
    fields = dict(cpu_model='Host CPU', cpu_cores=6, cpu_threads=12, memory_mb=262030,
                  selectel_inventory=snapshot)
    result = hardware(fields)
    assert dict(result['fields'])['Процессор'] == 'Host CPU'
    assert dict(result['fields'])['Память по данным хоста'] == '262030 МиБ'
    assert result['disks'] == [dict(count=4, capacity='6 TB', kind='HDD'),
                               dict(count=2, capacity='480 GB', kind='SSD')]
    assert result['disk_count'] == 6
    assert hardware({'cpu_model': 'Standalone'})['fields'] == [('Процессор', 'Standalone')]
    assert hardware({}) is None
    assert hardware({'physical_disks': [{'name': 'datastore', 'size_bytes': 123}]}) is None


def test_explicit_configuration_is_split_without_inventing_dimm_count():
    hardware = importlib.import_module(package.__name__ + '.hardware_display').panel
    result = hardware({'selectel_inventory': {'sections': {'hardware': {'data': {
        'config_name': 'AMD Ryzen 7 3700X: 8 x 3.6GHz, 32 GB DDR4 non-ECC, 2 x 500 GB SSD NVMe M.2'}}}}})
    assert dict(result['fields'])['Установленная память'] == '32 GB DDR4 non-ECC'
    assert result['disks'] == [dict(count=2, capacity='500 GB', kind='SSD')]
    assert 'Конфигурация Selectel' not in dict(result['fields'])
