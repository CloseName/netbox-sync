"""Structural evidence must distinguish missing/invalid data without exposing values."""
import json

import pytest

from deploy import selectel_hardware_evidence as evidence


def canonical(kind, value):
    return value if isinstance(value, str) and value.strip() and value != 'unknown' else None


def test_missing_root_identity_is_not_component_or_provider_identity():
    section = dict(status='collected', retained=False, data={
        'hw_uuid': 'PRIVATE-ID', 'serial': None, 'service_tag': 'unknown',
        'system_uuid': '', 'disk': [{'serial': 'PRIVATE-DISK'}],
        'board': [{'serial': 'PRIVATE-BOARD'}], 'password': 'PRIVATE-PASSWORD'})
    result = evidence.section_shape(section, canonical)
    assert result['parser_eligible'] is True
    assert result['identity_fields'] == dict(serial='null', service_tag='invalid_or_placeholder', system_uuid='empty')
    assert result['component_serial_counts']['disk'] == {'present': 1, 'nonempty_scalar': 1}
    assert result['component_serial_counts']['board']['nonempty_scalar'] == 1
    assert result['provider_hw_uuid_present'] is True
    assert 'PRIVATE' not in json.dumps(result) and 'password' not in json.dumps(result)


@pytest.mark.parametrize('status,retained', [('access_denied', False), ('collected', True), ('partial', False)])
def test_retained_or_unavailable_sections_are_not_parser_eligible(status, retained):
    result = evidence.section_shape(dict(status=status, retained=retained, data={'serial': 'PRIVATE'}), canonical)
    assert result['identity_fields']['serial'] == 'valid_format'
    assert result['parser_eligible'] is False
    assert 'PRIVATE' not in json.dumps(result)


def test_absent_wrong_shape_and_limits_are_explicit():
    assert evidence.section_shape(None, canonical)['section_present'] is False
    assert evidence.section_shape(dict(status='collected', data=[]), canonical)['data_type'] == 'array'
    assert evidence.section_shape(dict(status='PRIVATE', data={'serial': {}}), canonical)['status'] == 'unknown'
    assert evidence.section_shape(dict(data={'serial': {}}), canonical)['identity_fields']['serial'] == 'wrong_type'
    with pytest.raises(ValueError):
        evidence.section_shape(dict(data={'disk': [{}] * 2001}), canonical)


def test_report_executes_reviewed_source_as_argument_without_stdin_or_writes():
    calls = []
    def manage(*args):
        calls.append(args)
        assert args[:2] == ('shell', '-c')
        assert 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY' in args[2]
        return 'loaded config PRIVATE\nSELECTEL_HARDWARE_SHAPE:' + json.dumps(
            dict(account='29916', writes_performed=False, scope='stored_normalized_inventory', resources=[]))
    assert evidence.report(manage, '29916')['writes_performed'] is False
    assert len(calls) == 1
    with pytest.raises(ValueError):
        evidence.report(lambda *args: pytest.fail('No command'), '29916; dangerous')
