"""Narrow first-run control: protected NetBox state, no DB or source credentials."""
import json
import logging
import os
import subprocess
import sys
from .bootstrap_state import BootstrapStore
from .bootstrap_setup import Preparation
from .discovery_worker import _drop_privileges, _safe_environment
from .local_control import ControlError, serve
from .source_lifecycle import apply_lock
from .child_process import child_process, stop_child

PROBE_TIMEOUT = 45


def run_probe(value):
    try:
        with child_process(subprocess.Popen, [sys.executable, '-B', '-m', 'netbox_sync.bootstrap_probe'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=_safe_environment(), preexec_fn=_drop_privileges(10001, 10001)) as process:
            try:
                output, _ = process.communicate(json.dumps(value).encode(), timeout=PROBE_TIMEOUT)
            except subprocess.TimeoutExpired:
                detail = stop_child(process)
                logging.getLogger(__name__).warning(json.dumps({
                    'code': 'BOOTSTRAP_PROBE_TIMEOUT', **detail}, sort_keys=True))
                return {'safe_code': 'VALIDATION_UNAVAILABLE', 'checks': []}
            if process.returncode or len(output) > 16384:
                raise ValueError()
            return json.loads(output)
    except Exception:
        return {'safe_code': 'VALIDATION_UNAVAILABLE', 'checks': []}


class BootstrapControl:
    def __init__(self, store, lock_path, probe=run_probe):
        self.store, self.lock_path, self.probe = store, lock_path, probe

    def __call__(self, payload):
        action = payload.get('action')
        if action == 'registration-cluster':
            from .catalog_creation import CatalogCreation
            from .bootstrap_probe import ProbeError
            if set(payload) != {'action','operation_id','name','site_id','cluster_type_id'}:
                raise ControlError('BOOTSTRAP_INVALID')
            command = dict(action='catalog-create', operation_id=payload['operation_id'], kind='cluster',
                object=dict(name=payload['name'], type=payload['cluster_type_id'],
                            scope_type='dcim.site', scope_id=payload['site_id']), confirm=True)
            try:
                with apply_lock(self.lock_path):
                    result = CatalogCreation(self.store).execute(command, registration=True)
                # Another intent may have reached NetBox first. Its journal is not
                # evidence that this actor/source registration created the cluster.
                if result.get('operation_id') != payload['operation_id']:
                    return {'status':'EXISTS_REVIEW_REQUIRED','item':result.get('item')}
                return result
            except ProbeError as exc:
                return {'error':exc.code}
        if action in ('catalog-create','catalog-reconcile'):
            from .catalog_creation import CatalogCreation
            from .bootstrap_probe import ProbeError
            try:
                with apply_lock(self.lock_path):return CatalogCreation(self.store).execute(payload)
            except ProbeError as exc:return {'error':exc.code}
        if action == 'catalog' and set(payload)=={'action','query'}:
            from .bootstrap_state import runtime_netbox
            from contextlib import ExitStack
            import fcntl
            with ExitStack() as cleanup:
                # Four cross-process read slots, independent of the shared apply
                # lock. A catalog request never stops a running operation.
                for slot in range(4):
                    fd=os.open('/tmp/netbox-sync-catalog-'+str(slot)+'.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
                    try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError: os.close(fd);continue
                    cleanup.callback(os.close,fd);break
                else: return {'error':'BUSY'}
                url,token=runtime_netbox(self.store.path,'read')
                try:
                    result=subprocess.run([sys.executable,'-B','-m','netbox_sync.netbox_catalog'],
                        input=json.dumps({'url':url,'read_token':token,'query':payload['query']}).encode(),
                        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=30,check=True,
                        env=_safe_environment(),preexec_fn=_drop_privileges(10001,10001))
                    if len(result.stdout)>24576: raise ValueError()
                    return json.loads(result.stdout)
                except Exception: return {'error':'NETWORK_UNREACHABLE'}
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
