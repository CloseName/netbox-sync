"""Periodic collection with stored keys and current root-authorized egress policy."""
import os
import time
from .bootstrap_state import BootstrapStore
from .local_control import request
from .pfsense_control import handle, state_root


def tick(store, lock_path):
    root = state_root(store)
    if not root.exists(): return
    if root.is_symlink(): raise ValueError('Invalid state directory')
    for path in sorted(root.glob('*.json')):
        if not path.stem.isdecimal(): continue
        try:
            policy = request('/run/netbox-sync-pfsense-policy/worker.sock', {'action':'policy'})['result']['effective']
            handle(store, lock_path, dict(action='pfsense', operation='collect',
                vm_id=int(path.stem), session=None, data={}), scheduled_policy=policy)
        except Exception as error:
            if getattr(error, 'code', '') == 'SOURCE_APPLY_ACTIVE': return
            # Do not emit keys, server responses, or configuration into logs.
            import logging
            logging.getLogger(__name__).warning('pfSense scheduled collection deferred: VM %s', path.stem)


def main():
    store = BootstrapStore(os.environ.get('NETBOX_SYNC_NETBOX_STATE_DIR', '/var/lib/netbox-sync/netbox'))
    lock = os.environ.get('NETBOX_SYNC_APPLY_LOCK_PATH', '/run/netbox-sync-lock/apply.lock')
    while True:
        try: tick(store, lock)
        except Exception:
            import logging
            logging.getLogger(__name__).warning('pfSense scheduler waiting for control services')
        time.sleep(30)


if __name__ == '__main__': main()
