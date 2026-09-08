"""DB-only lifecycle coordinator; it never mounts source or NetBox secrets."""
import os
from .local_control import request, serve, ControlError
from .source_lifecycle import LifecycleStore
from .lifecycle_protocol import handle_lifecycle


class BrokerCleanup:
    def __init__(self, path):
        self.path = path

    def remove_owned(self, keys):
        result = request(self.path, {'action': 'remove_owned', 'keys': keys})
        if type(result.get('removed')) is not bool:
            raise ControlError()
        return result['removed']


def main():
    store = LifecycleStore(os.environ.get('NETBOX_SYNC_LIFECYCLE_WRITER_DSN', ''),
        os.environ.get('NETBOX_SYNC_REGISTRY_SCHEMA', ''),
        os.environ.get('NETBOX_SYNC_APPLY_LOCK_PATH', '/run/netbox-sync-lock/apply.lock'))
    broker = BrokerCleanup(os.environ.get('NETBOX_SYNC_BROKER_SOCKET', '/run/netbox-sync-broker/broker.sock'))
    serve(os.environ.get('NETBOX_SYNC_LIFECYCLE_SOCKET', '/run/netbox-sync-lifecycle/worker.sock'),
          lambda payload: handle_lifecycle(store, broker, payload))


if __name__ == '__main__':
    main()
