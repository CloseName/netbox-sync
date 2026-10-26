"""Validation evidence is structural and excludes arbitrary exception contents."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('validation_detail', Path(__file__).parents[1] / 'deploy/netbox_guard/validation_detail.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_fields_codes_and_model_are_projected_without_values():
    exc = SimpleNamespace(error_dict={
        'serial': [SimpleNamespace(code='max_length', message='SECRET', params={'value': 'PRIVATE'})],
        'private_field_name': [SimpleNamespace(code='PRIVATE')],
    })
    obj = SimpleNamespace(_meta=SimpleNamespace(label_lower='dcim.device'), pk=28)
    result = module.details(exc, obj, 'full_clean')
    assert result['model'] == 'dcim.device' and result['object_id'] == 28
    assert {'field': 'serial', 'code': 'max_length'} in result['issues']
    assert not any(s in json.dumps(result) for s in ('SECRET', 'PRIVATE', 'private_field_name'))


def test_validation_details_are_bounded():
    exc = SimpleNamespace(error_dict={'name': [SimpleNamespace(code='invalid') for _ in range(100)]})
    obj = SimpleNamespace(_meta=SimpleNamespace(label_lower='private.model'), pk=None)
    result = module.details(exc, obj, 'full_clean')
    assert result['model'] == 'unknown' and len(result['issues']) <= 12


def test_guard_and_sync_use_same_closed_contract():
    from netbox_sync import selectel_validation as wire
    assert (wire.MODELS, wire.FIELDS, wire.CODES) == (module.MODELS, module.FIELDS, module.CODES)
    value = {'model': 'private.model', 'object_id': True, 'phase': 'PRIVATE',
             'issues': [{'field': 'private-field', 'code': 'PRIVATE', 'message': 'SECRET'}]*100}
    result = wire.validation_detail(value)
    assert len(result['issues']) == 12 and 'object_id' not in result
    assert not any(s in json.dumps(result) for s in ('PRIVATE', 'SECRET', 'private'))


def test_validation_details_survive_public_projection():
    from netbox_sync.selectel_control import public
    detail = {'model': 'dcim.device', 'object_id': 28, 'phase': 'full_clean',
              'issues': [{'field': 'serial', 'code': 'max_length'}]}
    result = public({'import_diagnostic': {'reason': 'OBJECT_VALIDATION', 'validation': detail}})
    assert result['import_diagnostic']['validation'] == detail
