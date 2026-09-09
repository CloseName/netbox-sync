"""Durable first-run truth in one root-protected, atomically replaced document.

No credential is returned by the public projection. This storage belongs only to
bootstrap control and is backed up with the existing secrets/netbox directory.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import time
from urllib.parse import urlsplit
from uuid import uuid4
from .local_control import ControlError

STATES = frozenset({'FRESH', 'CONFIGURED', 'VALIDATING', 'VALIDATED', 'READY', 'ATTENTION'})


def checked_read(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 32768
                or (os.name == 'posix' and (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600))):
            raise ControlError('BOOTSTRAP_INVALID')
        raw = os.read(descriptor, 32769)
        value = json.loads(raw)
        if value.get('format') != 1 or value.get('status') not in STATES:
            raise ControlError('BOOTSTRAP_INVALID')
        return value
    finally:
        os.close(descriptor)


class BootstrapStore:
    def __init__(self, root, clock=time.time):
        self.root = Path(root)
        self.path = self.root / 'bootstrap.json'
        self.clock = clock

    @contextmanager
    def locked(self):
        import fcntl
        info = self.root.lstat()
        if (not stat.S_ISDIR(info.st_mode) or self.root.is_symlink()
                or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700):
            raise ControlError('BOOTSTRAP_INVALID')
        descriptor = os.open(self.root / 'bootstrap.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            raise ControlError('BOOTSTRAP_BUSY') from None
        try:
            yield
        finally:
            os.close(descriptor)

    def read(self):
        try:
            return checked_read(self.path)
        except FileNotFoundError:
            return {'format': 1, 'revision': 0, 'status': 'FRESH', 'url': '',
                    'read_token': '', 'apply_token': '', 'completed': False,
                    'safe_code': None, 'checks': [], 'validated_at': None}

    def write(self, value):
        temporary = self.root / ('bootstrap-' + uuid4().hex + '.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            raw = json.dumps(value, separators=(',', ':')).encode()
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.root, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def public(value):
        return {key: value[key] for key in ('revision', 'status', 'url', 'completed', 'safe_code', 'checks', 'validated_at')} | {
            'read_token_present': bool(value['read_token']), 'apply_token_present': bool(value['apply_token']), 'preparation': value.get('preparation'),
            'access_checks': value.get('access_checks', [])}

    def status(self):
        with self.locked():
            value = self.read()
            if value['status'] == 'VALIDATING' and self.clock() - value['validation_started'] > 60:
                value.update(status='ATTENTION', safe_code='VALIDATION_INTERRUPTED', checks=[])
                self.write(value)
            setup = value.get('preparation', {})
            if setup.get('status') == 'RUNNING' and self.clock() - setup.get('started_at', 0) > 240:
                setup.update(status='UNCERTAIN', local_secret='NOT_STORED')
                self.write(value)
            return self.public(value)

    def configure(self, payload):
        if set(payload) != {'action', 'revision', 'url', 'read_token', 'apply_token', 'replace_credentials'}:
            raise ControlError('BOOTSTRAP_INVALID')
        url = payload['url']
        try:
            parts = urlsplit(url)
            valid = (parts.scheme == 'https' and parts.hostname and not parts.username and not parts.password
                     and not parts.query and not parts.fragment and parts.path in ('', '/'))
            if parts.port is not None and not 1 <= parts.port <= 65535:
                valid = False
        except (ValueError, TypeError):
            valid = False
        tokens = (payload['read_token'], payload['apply_token'])
        if (not valid or len(url) > 2048 or any(not isinstance(token, str) or not 8 <= len(token) <= 4096
                or any(ord(char) < 33 or ord(char) > 126 for char in token) for token in tokens)
                or tokens[0] == tokens[1] or type(payload['replace_credentials']) is not bool):
            raise ControlError('BOOTSTRAP_INVALID')
        with self.locked():
            value = self.read()
            if type(payload['revision']) is not int or payload['revision'] != value['revision']:
                raise ControlError('BOOTSTRAP_CONFLICT')
            url = url.rstrip('/')
            if value['completed'] and url != value['url']:
                raise ControlError('BOOTSTRAP_INVALID')
            if value['read_token'] and not payload['replace_credentials']:
                raise ControlError('BOOTSTRAP_CONFLICT')
            if value['status'] == 'VALIDATING' or value.get('preparation', {}).get('status') == 'RUNNING':
                raise ControlError('BOOTSTRAP_BUSY')
            if value.get('preparation') and url != value['url']:
                raise ControlError('BOOTSTRAP_INVALID')
            value.update(revision=value['revision'] + 1, status='CONFIGURED', url=url,
                         read_token=tokens[0], apply_token=tokens[1], safe_code=None,
                         checks=[], access_checks=[], validated_at=None)
            self.write(value)
            return self.public(value)

    def validate(self, revision, probe):
        with self.locked():
            value = self.read()
            if type(revision) is not int or value['revision'] != revision:
                raise ControlError('BOOTSTRAP_CONFLICT')
            if value.get('preparation', {}).get('status') == 'RUNNING':raise ControlError('BOOTSTRAP_BUSY')
            if value['status'] == 'VALIDATING' or (value['status'] == 'VALIDATED' and self.clock() - value['validated_at'] <= 300):
                return self.public(value)
            if not value['read_token']:
                raise ControlError('BOOTSTRAP_INVALID')
            attempt = uuid4().hex
            value.update(status='VALIDATING', validation_started=self.clock(), validation_id=attempt, safe_code=None)
            self.write(value)
        try:
            result = probe(value)
        except Exception:
            result = {'safe_code': 'VALIDATION_UNAVAILABLE', 'checks': []}
        with self.locked():
            current = self.read()
            if current['revision'] != revision or current['status'] != 'VALIDATING' or current.get('validation_id') != attempt:
                return self.public(current)
            allowed = {'NETWORK_UNREACHABLE','TLS_FAILED','AUTH_FAILED','PERMISSION_DENIED',
                       'RESPONSE_INVALID','PREREQUISITES_MISSING','DESTINATION_DENIED','VALIDATION_UNAVAILABLE'}
            from .bootstrap_probe import FIELDS
            checks = result.get('checks') if isinstance(result, dict) else None
            valid_checks = (isinstance(checks, list) and len(checks) == len(FIELDS)
                and all(isinstance(check, dict) and set(check) == {'name', 'type', 'models', 'ok'}
                    and check['name'] == name and check['type'] == kind
                    and check['models'] == list(models) and type(check['ok']) is bool
                    for check, (name, (kind, models)) in zip(checks, FIELDS.items())))
            code = result.get('safe_code', 'VALIDATION_UNAVAILABLE') if isinstance(result, dict) else 'VALIDATION_UNAVAILABLE'
            if code is None and (not valid_checks or not all(check['ok'] for check in checks)):
                code = 'VALIDATION_UNAVAILABLE'
            if code is not None and code not in allowed:
                code = 'VALIDATION_UNAVAILABLE'
            access = result.get('access_checks', []) if isinstance(result, dict) else []
            allowed_access = {'network','tls','read_auth','apply_auth','permissions','prerequisites'}
            current['access_checks'] = [c for c in access if isinstance(c, dict) and set(c)=={'name','status'} and c['name'] in allowed_access and c['status'] in ('passed','failed','not_run','preliminary','pending')] if isinstance(access,list) else []
            current.update(status='VALIDATED' if code is None else 'ATTENTION', safe_code=code,
                           checks=checks if valid_checks else [], validated_at=self.clock() if code is None else None)
            self.write(current)
            return self.public(current)

    def finish(self, revision):
        with self.locked():
            value = self.read()
            if type(revision) is not int or value['revision'] != revision:
                raise ControlError('BOOTSTRAP_CONFLICT')
            if value['status'] == 'READY':
                return self.public(value)
            if value['status'] != 'VALIDATED' or self.clock() - value['validated_at'] > 300:
                raise ControlError('BOOTSTRAP_NOT_READY')
            value.update(status='READY', completed=True)
            self.write(value)
            return self.public(value)


def runtime_netbox(path, kind):
    """Trusted worker-only read; no environment inference of readiness."""
    if kind not in ('read', 'apply'):
        raise ControlError('BOOTSTRAP_INVALID')
    try:
        value = checked_read(path)
        if value['status'] != 'READY':
            raise ControlError('BOOTSTRAP_NOT_READY')
        return value['url'], value[kind + '_token']
    except ControlError:
        raise
    except Exception:
        raise ControlError('BOOTSTRAP_NOT_READY') from None
