"""Closed diagnostics for exceptions after the account transaction rolls back."""
REASONS = frozenset({
    'PROVIDER_COMPLETE_NETBOX_VISIBILITY_REQUIRED', 'PROVIDER_NATIVE_SCOPE_CONFLICT',
    'PROVIDER_PLACEMENT_IDENTITY_REQUIRED', 'PROVIDER_IDENTITY_INVALID',
    'PROVIDER_ACCOUNT_MISMATCH', 'PROVIDER_NONCE_CONFLICT', 'PROVIDER_ACCOUNT_DELETED',
    'PROVIDER_HISTORICAL_RUN_RETIRED', 'PROVIDER_REVIEW_STALE', 'PERMISSION_DENIED',
    'PROVIDER_NATIVE_PERMISSIONS_REQUIRED', 'PROVIDER_FIELD_OWNED',
    'PROVIDER_PROJECTION_UNCLAIMED', 'PROVIDER_IPAM_FIELD_OWNED',
})


def reason(exc):
    """Never return exception messages, validation values or SQL text."""
    if str(exc) in REASONS:
        return str(exc)
    return {'IntegrityError': 'DATABASE_CONSTRAINT', 'ValidationError': 'OBJECT_VALIDATION',
            'ValueError': 'INPUT_OR_POLICY_REJECTED', 'TypeError': 'INPUT_SHAPE_INVALID',
            'KeyError': 'INPUT_SHAPE_INVALID', 'AttributeError': 'INPUT_SHAPE_INVALID',
            'DependencyGuardBlocked': 'POLICY_REJECTED'}.get(type(exc).__name__, 'IMPORT_REJECTED')
