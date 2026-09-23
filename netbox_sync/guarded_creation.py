"""Optional creation receipts without changing planning, reads or UPDATE semantics.

Only an explicitly pinned guard installation enables this facade. Creation nonces
are scoped to the durable run and endpoint sequence; the existing no-reapply gate
still forbids restarting a partially executed run. This is not a retry mechanism.
"""
from uuid import UUID, uuid5
from .retirement_transport import GuardClient, GuardTransportError
from .netbox_auth import authorization
from .host_registration import identity_placement

RESOURCES = {
    'dcim.devices': 'device', 'dcim.interfaces': 'interface',
    'dcim.mac_addresses': 'mac', 'virtualization.virtual_machines': 'vm',
    'virtualization.interfaces': 'vminterface', 'virtualization.virtual_disks': 'disk',
    'ipam.ip_addresses': 'ip',
}


class CreationEndpoint:
    def __init__(self, endpoint, client, path, source, cluster, run):
        self.endpoint, self.client, self.path = endpoint, client, path
        self.source, self.cluster, self.run = source, cluster, run
        self.sequence = 0

    def __getattr__(self, name): return getattr(self.endpoint, name)

    def create(self, **fields):
        # A counter is deliberately independent of payload content: a changed
        # payload at the same run/endpoint position conflicts with its receipt.
        self.sequence += 1
        nonce = uuid5(self.run, f'{self.source}:{self.path}:{self.sequence}')
        result = self.client.create(nonce, self.source, RESOURCES[self.path], self.cluster, fields)
        return self.endpoint.return_obj(result, self.endpoint.api, self.endpoint)


class CreationNamespace:
    def __init__(self, namespace, prefix, client, source, cluster, run):
        self.namespace, self.prefix, self.client = namespace, prefix, client
        self.source, self.cluster, self.run = source, cluster, run
        self.cache = {}

    def __getattr__(self, name):
        if name not in self.cache:
            endpoint = getattr(self.namespace, name)
            path = self.prefix + '.' + name
            self.cache[name] = (CreationEndpoint(endpoint, self.client, path, self.source, self.cluster, self.run)
                                if path in RESOURCES else endpoint)
        return self.cache[name]


class GuardedCreation:
    def __init__(self, api, client, source, cluster, run):
        self.api = api
        for name in ('dcim', 'virtualization', 'ipam'):
            setattr(self, name, CreationNamespace(getattr(api, name), name, client, source, cluster, UUID(str(run))))

    def __getattr__(self, name): return getattr(self.api, name)


def for_run(api, config, *, instance, run_id, url, token):
    if not instance: return api
    try:
        run = UUID(str(run_id)); instance = str(UUID(str(instance)))
    except (ValueError, TypeError):
        raise GuardTransportError('GUARD_RUN_REQUIRED') from None
    _, cluster = identity_placement(config.settings)
    if type(cluster) is not int or cluster <= 0:
        raise GuardTransportError('GUARD_PLACEMENT_REQUIRED')
    client = GuardClient(api.http_session, url, authorization(token), instance)
    client.capabilities()
    return GuardedCreation(api, client, config.source_instance, cluster, run)
