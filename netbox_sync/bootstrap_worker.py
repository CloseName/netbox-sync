"""Narrow first-run control: protected NetBox state, no DB or source credentials."""
import json
import os
import subprocess
import sys
from .bootstrap_state import BootstrapStore
from .bootstrap_setup import Preparation
from .discovery_worker import _drop_privileges, _safe_environment
from .local_control import ControlError, serve
from .source_lifecycle import apply_lock


def run_probe(value):
    try:
        result = subprocess.run([sys.executable, '-B', '-m', 'netbox_sync.bootstrap_probe'],
            input=json.dumps(value).encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=45, check=True, env=_safe_environment(), preexec_fn=_drop_privileges(10001, 10001))
        if len(result.stdout) > 16384:
            raise ValueError()
        return json.loads(result.stdout)
    except Exception:
        return {'safe_code': 'VALIDATION_UNAVAILABLE', 'checks': []}


class BootstrapControl:
    def __init__(self, store, lock_path, probe=run_probe):
        self.store, self.lock_path, self.probe = store, lock_path, probe

    def __call__(self, payload):
        action = payload.get('action')
        if action == 'status' and set(payload) == {'action'}:
            return self.store.status()
        if action in ('prerequisites-plan', 'prerequisites-cancel') and set(payload)=={'action','revision'}:
            setup = Preparation(self.store)
            return setup.plan(payload['revision']) if action=='prerequisites-plan' else setup.cancel(payload['revision'])
        if action == 'prerequisites-apply' and set(payload)=={'action','revision','digest','confirm','setup_token'}:
            with apply_lock(self.lock_path):
                return Preparation(self.store).apply(payload)
        if action == 'configure':
            with apply_lock(self.lock_path):
                return self.store.configure(payload)
        if action in ('validate', 'finish') and set(payload) == {'action', 'revision'}:
            if action == 'validate':
                return self.store.validate(payload['revision'], self.probe)
            with apply_lock(self.lock_path):
                return self.store.finish(payload['revision'])
        raise ControlError('BOOTSTRAP_INVALID')


def main():
    control = BootstrapControl(BootstrapStore(os.environ.get('NETBOX_SYNC_NETBOX_STATE_DIR', '/var/lib/netbox-sync/netbox')),
        os.environ.get('NETBOX_SYNC_APPLY_LOCK_PATH', '/run/netbox-sync-lock/apply.lock'))
    serve(os.environ.get('NETBOX_SYNC_BOOTSTRAP_SOCKET', '/run/netbox-sync-bootstrap/worker.sock'), control, concurrent=True)


if __name__ == '__main__':
    main()
