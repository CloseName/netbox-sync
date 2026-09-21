"""Auth/policy worker with bounded verified directory access; public peer socket and root-only local control."""
import json
import multiprocessing
import os
import signal
import sys
from .auth_store import AuthStore
from .auth_policy import AuthError
from .api.settings import ApiSettings
from .local_control import serve, request

SOCKET = '/run/netbox-sync-auth/worker.sock'
ADMIN_SOCKET = '/run/netbox-sync-auth-admin/worker.sock'


def store():
    return AuthStore(os.environ.get('NETBOX_SYNC_AUTH_WRITER_DSN', ''),
                     os.environ.get('NETBOX_SYNC_REGISTRY_SCHEMA', ''),
                     ApiSettings.from_environment().egress_policy)


def admin():
    serve(ADMIN_SOCKET, lambda payload: store().call(payload, root=True), allowed_uid=0)


def directory_sync():
    import time
    while True:
        try: store().call({'action':'ldap.sync.due'},root=True)
        except Exception: pass  # Safe error and last success are persisted by AuthStore.
        time.sleep(30)


def main():
    if len(sys.argv) > 1:
        if os.geteuid() != 0:
            raise SystemExit('Root required')
        # Only nonsecret commands in argv. Invitation is captured by host control
        # into a new 0600 file, never a daemon log or a command line.
        action = sys.argv[1]
        payload = {'action': action}
        if action == 'managed':
            payload['ceiling'] = sys.argv[2] if len(sys.argv) == 3 else ''
        try:
            result = request(ADMIN_SOCKET, payload)['result']
        except Exception:
            raise SystemExit('Administrative control unavailable') from None
        print(json.dumps(result))
        return
    def stop(_signal, _frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    process = multiprocessing.Process(target=admin)
    process.start()
    sync_process=multiprocessing.Process(target=directory_sync)
    sync_process.start()
    try:
        serve(SOCKET, lambda payload: store().call(payload), allowed_uid=10001, additional_uids=(0,))
    finally:
        sync_process.terminate()
        sync_process.join(5)
        process.terminate()
        process.join(5)


if __name__ == '__main__':
    main()
