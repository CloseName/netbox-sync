"""Admin-only account control, durable root-owned secrets and asynchronous runs."""
import json
import os
import re
import stat
import subprocess
import sys
import time
from uuid import uuid4
from .local_control import ControlError
from .bootstrap_state import runtime_netbox

PUBLIC = ('account', 'name', 'username', 'status', 'started_at', 'finished_at', 'error', 'summary', 'run_id')


def public(state):
    return {k: state[k] for k in PUBLIC if k in state}


def running(state):
    if state.get('status') != 'running': return False
    if time.time() - state.get('started_at', 0) > 3600: return False
    if time.time() - state.get('started_at', 0) < 5: return True
    try:
        from pathlib import Path
        return state['run_id'].encode() in Path('/proc', str(int(state['pid'])), 'cmdline').read_bytes().split(b'\0')
    except (OSError, KeyError, ValueError, TypeError):
        return False


def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if info.st_uid or stat.S_IMODE(info.st_mode) != 0o600 or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 131072:
            raise ControlError('BOOTSTRAP_INVALID')
        return json.load(stream)


def write(path, value):
    tmp = path.parent / (uuid4().hex + '.tmp')
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if tmp.exists(): tmp.unlink()


def root(store):
    path = store.root / 'selectel'
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise ControlError('BOOTSTRAP_INVALID')
    return path


def handle(store, lock_path, payload):
    from .api.auth import AuthClient
    from .api.selectel import Account
    if set(payload) != {'action', 'operation', 'session', 'data'} or payload['operation'] not in ('list', 'save', 'collect'):
        raise ControlError('CONTROL_REQUEST_INVALID')
    AuthClient('/run/netbox-sync-auth/worker.sock').call('authorize', session=payload['session'],
        permission='bootstrap.manage', audit=payload['operation'] != 'list')
    operation, data = payload['operation'], payload['data']
    with store.locked():
        base = root(store)
        url, _ = runtime_netbox(store.path, 'read')
        if operation == 'list':
            items = []
            for p in sorted(base.glob('*.json')):
                if re.fullmatch(r'[0-9]{1,20}', p.stem):
                    state = read(p)
                    if state.get('status') == 'running' and not running(state):
                        state.update(status='attention', error='RUN_INTERRUPTED')
                    items.append({**public(state), 'url': url.rstrip('/') + '/plugins/netbox-sync-guard/providers/' + p.stem + '/'})
            return {'items': items, 'import_ready': (base / 'netbox-token.json').is_file()}
        if not isinstance(data, dict) or not re.fullmatch(r'[0-9]{1,20}', str(data.get('account', ''))):
            raise ControlError('CONTROL_REQUEST_INVALID')
        path = base / (data['account'] + '.json')
        state = read(path) if path.exists() else {}
        if running(state):
            return {'error': 'RUN_ACTIVE'}
        if operation == 'save':
            if not state and len(list(base.glob('[0-9]*.json'))) >= 100:
                return {'error': 'ACCOUNT_LIMIT'}
            parsed = Account(**data)
            if not parsed.name.strip() or not parsed.username.strip():
                raise ControlError('CONTROL_REQUEST_INVALID')
            state.update(account=parsed.account, name=parsed.name.strip(), username=parsed.username.strip(),
                         password=parsed.password.get_secret_value(), status='configured', error=None)
            write(path, state)
            return public(state)
        if not state or not (base / 'netbox-token.json').is_file():
            return {'error': 'SETUP_REQUIRED'}
        if len(list(base.glob('[0-9]*.json'))) > 100:
            return {'error': 'ACCOUNT_LIMIT'}
        state.update(status='running', started_at=time.time(), error=None, run_id=str(uuid4()))
        write(path, state)
        try:
            # No credentials in argv, environment or logs. Root runner reads protected state.
            process = subprocess.Popen([sys.executable, '-B', '-m', 'netbox_sync.selectel_runner',
                str(store.root), state['account'], state['run_id'], str(lock_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, close_fds=True)
            state['pid'] = process.pid
            write(path, state)
        except OSError:
            state.update(status='attention', error='RUN_START_FAILED'); write(path, state)
        return public(state)
