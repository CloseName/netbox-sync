"""Closed structural evidence for Selectel model validation; never error text."""
MODELS = frozenset({'dcim.device', 'dcim.site', 'dcim.region', 'dcim.manufacturer',
    'dcim.devicetype', 'dcim.devicerole', 'virtualization.virtualmachine', 'extras.customfield'})
FIELDS = frozenset({'name', 'slug', 'serial', 'status', 'site', 'region', 'cluster',
    'device', 'device_type', 'role', 'tenant', 'rack', 'location', 'position', 'face',
    'vcpus', 'memory', 'disk', 'custom_field_data', 'description', 'comments',
    'manufacturer', 'model', 'type', 'group_name', 'required', 'unique', '__all__'})
CODES = frozenset({'blank', 'null', 'invalid', 'invalid_choice', 'unique', 'unique_together',
    'max_length', 'min_length', 'max_value', 'min_value', 'max_digits',
    'max_decimal_places', 'max_whole_digits'})


def details(exc, obj=None, phase='unknown'):
    model = getattr(getattr(obj, '_meta', None), 'label_lower', None)
    result = {'model': model if model in MODELS else 'unknown',
              'phase': phase if phase in {'full_clean', 'save'} else 'unknown', 'issues': []}
    pk = getattr(obj, 'pk', None)
    if type(pk) is int and pk > 0:
        result['object_id'] = pk
    errors = getattr(exc, 'error_dict', None)
    if not isinstance(errors, dict):
        errors = {'__all__': getattr(exc, 'error_list', [])}
    for key, values in errors.items():
        if not isinstance(values, (list, tuple)):
            continue
        for value in values:
            code = getattr(value, 'code', None)
            issue = {'field': key if isinstance(key, str) and key in FIELDS else 'other',
                     'code': code if isinstance(code, str) and code in CODES else 'unspecified'}
            if issue not in result['issues']:
                result['issues'].append(issue)
            if len(result['issues']) == 12:
                return result
    return result


def checked(obj, method, **kwargs):
    """Preserve the original exception and all validation/write behavior."""
    from django.core.exceptions import ValidationError
    try:
        return getattr(obj, method)(**kwargs)
    except ValidationError as exc:
        exc.selectel_validation_detail = details(exc, obj, method)
        raise
