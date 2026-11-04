"""Physical component lists must not be presented as scalar MiB/GiB values."""
import importlib
from pathlib import Path
import sys
from types import ModuleType


def test_physical_components_and_cloud_scalar_units():
    package = ModuleType('provider_presentation_fixture')
    package.__path__ = [str(Path(__file__).parents[1] / 'deploy/netbox_guard')]
    sys.modules[package.__name__] = package
    module = importlib.import_module(package.__name__ + '.resource_presentation')
    row = dict(kind='dedicated', project='', region='', server=True, sections={
        'hardware': {'data': {'ram': [{'name': '8 GB DDR4 ECC', 'count': 4}],
                              'disk': [{'name': '3840 GB SSD', 'count': 4}]}}})
    fields = dict(module.decorate(row, {})['fields'])
    assert fields['Модули памяти'] == '4 × 8 GB DDR4 ECC'
    assert fields['Физические диски'] == '4 × 3840 GB SSD'
    assert 'Память, МиБ' not in fields and 'Локальный диск, ГиБ' not in fields
    row['kind'] = 'cloud_vm'
    row['sections']['hardware']['data'] = {'ram': 2048, 'disk': 20}
    fields = dict(module.decorate(row, {})['fields'])
    assert fields['Память, МиБ'] == 2048 and fields['Локальный диск, ГиБ'] == 20
