"""Closed plan-revalidation diagnostics; never include inventory or secret values."""
import hashlib
import json

REASONS = frozenset({'OPERATION_MISSING', 'OPERATION_VERSION', 'OPERATION_EXPIRED',
    'OPERATION_STATUS', 'RESULT_MISSING', 'REVIEW_DIGEST', 'PLANNER_VERSION',
    'PLAN_DIGEST', 'PLAN_FORBIDDEN', 'SOURCE_IDENTITY'})
CATEGORIES = frozenset({'SOURCE_CONFIGURATION', 'TARGET_CONFIGURATION', 'PROVIDER_INVENTORY',
    'NETBOX_OBSERVATION', 'PLANNED_ACTIONS', 'PLAN_CONTRACT'})
FIELDS = {'source_fingerprint': 'SOURCE_CONFIGURATION', 'target_fingerprint': 'TARGET_CONFIGURATION',
    'provider_fingerprint': 'PROVIDER_INVENTORY', 'netbox_fingerprint': 'NETBOX_OBSERVATION',
    'actions': 'PLANNED_ACTIONS', 'planner_version': 'PLAN_CONTRACT', 'schema_version': 'PLAN_CONTRACT'}

def summary(plan):
    result = {key: plan.get(key) for key in FIELDS if key != 'actions'}
    result['actions'] = hashlib.sha256(json.dumps(plan.get('items', []), sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    return result

def differences(expected, actual):
    if not isinstance(expected, dict):
        return ['PLAN_CONTRACT']
    current = summary(actual)
    return sorted({category for key, category in FIELDS.items() if expected.get(key) != current.get(key)})

def safe_reason(value):
    return value if isinstance(value, str) and value in REASONS else None

def safe_categories(value):
    return sorted({item for item in value if isinstance(item, str) and item in CATEGORIES}) if isinstance(value, list) else []
