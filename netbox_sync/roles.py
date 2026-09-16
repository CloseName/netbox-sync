"""Fixed roadmap roles. No client role assertion is authoritative."""
READ = frozenset({'source.read', 'run.read', 'diagnostics.read'})
OPERATE = READ | {'source.plan', 'source.apply'}
ADMIN = OPERATE | {'catalog.create', 'policy.read', 'policy.write', 'source.probe',
    'source.register', 'source.configure', 'source.schedule', 'source.remove',
    'bootstrap.manage', 'identity.manage'}
ROLES = {'viewer': READ, 'operator': OPERATE, 'admin': ADMIN}

def permissions(role):
    return ROLES.get(role, frozenset())

def matrix():
    return {role: sorted(values) for role, values in ROLES.items()}
