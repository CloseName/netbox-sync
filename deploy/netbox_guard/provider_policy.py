"""Pure validation for operator-confirmed provider associations."""
import hashlib
import json
import re


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def identity(value, resource):
    if not isinstance(value, dict) or set(value) != {'account', 'kind', 'native_id', 'project', 'region'}:
        raise ValueError('PROVIDER_IDENTITY_INVALID')
    if resource not in ('device', 'vm'):
        raise ValueError('PROVIDER_TARGET_INVALID')
    for key, item in value.items():
        if not isinstance(item, str) or len(item) > 128 or (item and not re.fullmatch(r'[a-zA-Z0-9_.:-]+', item)):
            raise ValueError('PROVIDER_IDENTITY_INVALID')
    if not value['account'] or not value['native_id']:
        raise ValueError('PROVIDER_IDENTITY_INVALID')
    if value['kind'] == 'dedicated' and resource == 'device':
        key = ['selectel', value['account'], 'dedicated', value['native_id']]
    elif value['kind'] == 'cloud_vm' and resource == 'vm' and value['project'] and value['region']:
        key = ['selectel', value['account'], value['project'], value['region'], 'cloud_vm', value['native_id']]
    else:
        raise ValueError('PROVIDER_TARGET_INVALID')
    encoded = json.dumps(key, separators=(',', ':'))
    if len(encoded) > 512:
        raise ValueError('PROVIDER_IDENTITY_INVALID')
    return encoded


def proposed_claims(value, resource, serial=None):
    identity(value, resource)
    # No source identity, management IP, name, Site, scope or guest mutation.
    claims = {'custom_fields.selectel_refs': [dict(provider='selectel', **value)],
              'custom_fields.selectel_summary': f"Selectel / {value['account']} / {value['kind']} / {value['native_id']}"}
    if serial is not None:
        if resource != 'device' or not isinstance(serial, str) or not serial.strip() or len(serial) > 50:
            raise ValueError('PROVIDER_SERIAL_INVALID')
        if serial.strip().lower() in ('unknown', 'n/a', 'none', '0'):
            raise ValueError('PROVIDER_SERIAL_INVALID')
        claims['serial'] = serial
    return claims
