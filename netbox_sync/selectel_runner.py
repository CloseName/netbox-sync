"""Durable bounded account job. Provider reads run without root privileges."""
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from .bootstrap_state import BootstrapStore, runtime_netbox
from .local_control import ControlError
from .selectel_control import read, write, root
from .source_lifecycle import apply_lock
from .discovery_worker import _drop_privileges, _safe_environment
from .child_process import child_process, stop_child
from .selectel_payload import MAX_BYTES


def child_result(output, returncode, operation):
    # Once import started, an abnormal response cannot prove that no writes ran.
    def failure(code):
        return {'error': 'IMPORT_UNCONFIRMED' if operation == 'import' else code}
    if os.fstat(output.fileno()).st_size > MAX_BYTES:
        return failure('SELECTEL_RESULT_TOO_LARGE')
    if returncode:
        return failure('SELECTEL_COLLECTOR_EXITED')
    output.seek(0)
    try:
        result = json.load(output)
    except (ValueError, UnicodeError):
        return failure('SELECTEL_RESULT_INVALID')
    if not isinstance(result, dict):
        return failure('SELECTEL_RESULT_INVALID')
    if operation == 'collect' and 'error' not in result and not all(
            isinstance(result.get(k), dict) for k in ('document', 'registry', 'summary')):
        return failure('SELECTEL_RESULT_INVALID')
    return result


@contextmanager
def locked_store(store):
    # The launcher still holds this lock briefly after starting our process.
    with ExitStack() as stack:
        for attempt in range(101):
            try:
                stack.enter_context(store.locked())
                break
            except ControlError as exc:
                if exc.code != 'BOOTSTRAP_BUSY' or attempt == 100:
                    raise
                time.sleep(0.05)
        yield


def child(value, timeout):
    def sandbox():
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES + 4096, MAX_BYTES + 4096))
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
        _drop_privileges(10001, 10001)()
    with tempfile.TemporaryFile() as output:
        with child_process(subprocess.Popen, [sys.executable, '-B', '-m', 'netbox_sync.selectel_collect'],
                stdin=subprocess.PIPE, stdout=output, stderr=subprocess.DEVNULL,
                env=_safe_environment(), preexec_fn=sandbox) as process:
            try: process.communicate(json.dumps(value).encode(), timeout=timeout)
            except subprocess.TimeoutExpired:
                stop_child(process)
                return {'error': 'IMPORT_UNCONFIRMED' if value['operation'] == 'import' else 'RUN_TIMEOUT'}
        return child_result(output, process.returncode, value['operation'])


def main():
    store = BootstrapStore(sys.argv[1]); account, run_id, lock = sys.argv[2:]
    base = root(store); path = base / (account + '.json')
    try:
        # Per-account lock survives API timeout and prevents overlap after interrupted runs.
        with apply_lock(str(base / 'collection.lock')), apply_lock(str(base / (account + '.lock'))):
            with locked_store(store):
                state = read(path)
                if state['run_id'] != run_id: return
            url, _ = runtime_netbox(store.path, 'read')
            token = read(base / 'netbox-token.json')['token']
            access = dict(url=url, token=token, guard_instance=os.environ.get('NETBOX_SYNC_GUARD_INSTANCE', ''))
            result = child(dict(operation='preflight', **access), 90)
            if result.get('ready') is True:
                result = child(dict(operation='collect', account=account,
                    username=state['username'], password=state['password']), 2800)
            elif 'error' not in result:
                result = {'error': 'IMPORT_UNCONFIRMED'}
            if 'error' not in result:
                with apply_lock(lock):
                    url, _ = runtime_netbox(store.path, 'read')
                    token = read(base / 'netbox-token.json')['token']
                    imported = child(dict(operation='import', url=url, token=token,
                        guard_instance=os.environ.get('NETBOX_SYNC_GUARD_INSTANCE', ''),
                        payload=dict(account=account, nonce=run_id, document=result['document'], registry=result['registry'])), 90)
                if 'error' in imported: result = imported
                else: result = {'summary': {**result['summary'], **imported}}
    except Exception:
        result = {'error': 'RUN_INTERRUPTED_OR_BUSY'}
    # Do not expose exception bodies, provider payloads, or passwords.
    with locked_store(store):
        state = read(path)
        if state.get('run_id') != run_id: return
        if 'error' in result:
            state.update(status='attention', error=result['error'])
        else:
            state.update(status='completed', error=None, summary=result['summary'])
        state['finished_at'] = time.time()
        write(path, state)


if __name__ == '__main__': main()
