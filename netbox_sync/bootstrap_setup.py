"""Durable prerequisite plan/execution journal; NEVER persists the setup token."""
import json
import subprocess
import sys
import time
from uuid import uuid4
from .local_control import ControlError
from .discovery_worker import _drop_privileges, _safe_environment
from .netbox_auth import token_key
from .prerequisites import VERSION, FIELDS, digest


def isolated(value):
    try:
        result = subprocess.run([sys.executable, '-B', '-m', 'netbox_sync.bootstrap_setup_probe'],
            input=json.dumps(value).encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=18, check=True, env=_safe_environment(), preexec_fn=_drop_privileges(10001, 10001))
        if len(result.stdout) > 20000:raise ValueError()
        return json.loads(result.stdout)
    except Exception:return {'code': 'UNCERTAIN'}


class Preparation:
    def __init__(self, store, execute=isolated):
        self.store, self.execute = store, execute

    def read_fields(self, value):
        result = self.execute({'action': 'inspect', 'url': value['url'], 'token': value['read_token']})
        fields = result.get('fields')
        if not isinstance(fields, list) or [f.get('name') for f in fields] != list(FIELDS):
            raise ControlError('BOOTSTRAP_NOT_READY')
        return fields

    def plan(self, revision):
        with self.store.locked():
            value = self.store.read()
            self.check(value, revision)
            if not value['read_token']:raise ControlError('BOOTSTRAP_NOT_READY')
        fields = self.read_fields(value)
        with self.store.locked():
            current = self.store.read();self.check(current, revision)
            setup = current.get('preparation', {})
            uncertain = setup.get('uncertain')
            if uncertain and next(f for f in fields if f['name'] == uncertain)['status'] != 'missing':uncertain = None
            current['preparation'] = {'version': VERSION, 'status': 'UNCERTAIN' if uncertain else 'PLANNED',
                'fields': fields, 'digest': digest(revision, current['url'], fields), 'planned_at': self.store.clock(),
                'uncertain': uncertain, 'created': setup.get('created', []),
                'revocation': setup.get('revocation', 'NOT_ATTEMPTED'), 'local_secret': 'NOT_STORED'}
            self.store.write(current)
            return self.store.public(current)

    def check(self, value, revision):
        if type(revision) is not int or revision != value['revision']:raise ControlError('BOOTSTRAP_CONFLICT')
        if value['status'] == 'VALIDATING' or value.get('preparation', {}).get('status') == 'RUNNING':raise ControlError('BOOTSTRAP_BUSY')

    def cancel(self, revision):
        with self.store.locked():
            value = self.store.read();self.check(value, revision)
            setup = value.get('preparation', {})
            setup.update(status='CANCELLED', local_secret='NOT_STORED')
            value['preparation'] = setup;self.store.write(value)
            return self.store.public(value)

    def apply(self, payload):
        token = payload['setup_token']
        if not isinstance(token, str) or not 8 <= len(token) <= 4096 or any(ord(c)<33 or ord(c)>126 for c in token):raise ControlError('BOOTSTRAP_INVALID')
        try:key = token_key(token)
        except ValueError:raise ControlError('BOOTSTRAP_INVALID') from None
        with self.store.locked():
            value = self.store.read();self.check(value, payload['revision'])
            if any(token == value[k] or (key and key == token_key(value[k])) for k in ('read_token','apply_token')):raise ControlError('BOOTSTRAP_INVALID')
            setup = value.get('preparation', {})
            if (payload.get('confirm') is not True or setup.get('status') != 'PLANNED' or setup.get('digest') != payload['digest']
                or self.store.clock() - setup['planned_at'] > 300 or setup.get('uncertain')
                or any(f['status'] in ('conflict', 'provisioning') for f in setup['fields'])):raise ControlError('BOOTSTRAP_CONFLICT')
            run_id = uuid4().hex
            setup.update(status='RUNNING', run_id=run_id, started_at=self.store.clock(), revocation='NOT_ATTEMPTED', local_secret='MEMORY_ONLY')
            value['validated_at'] = None;value['status'] = 'ATTENTION';value['safe_code'] = 'PREREQUISITES_MISSING'
            self.store.write(value)
        started = time.monotonic()
        def save(**updates):
            with self.store.locked():
                current = self.store.read()
                if current.get('preparation', {}).get('run_id') != run_id:raise ControlError('BOOTSTRAP_CONFLICT')
                current['preparation'].update(updates);self.store.write(current)
        class Stop(Exception):pass
        try:
            fields = self.read_fields(value)
            if digest(value['revision'], value['url'], fields) != payload['digest']:
                save(status='STALE');raise Stop()
            identity = self.execute({'action':'identify', 'url':value['url'], 'token':token})
            if identity.get('code'):
                save(status='TOKEN_REJECTED');raise Stop()
            for field in fields:
                if field['status'] != 'missing':continue
                if time.monotonic()-started > 90:save(status='EXPIRED');raise Stop()
                # Durable marker BEFORE POST. Crash/timeout never permits a blind retry.
                save(uncertain=field['name'])
                result = self.execute({'action':'create', 'url':value['url'], 'token':token, 'name':field['name']})
                if result.get('code') not in ('CREATED','RECONCILE','REJECTED'):
                    save(status='UNCERTAIN');raise Stop()
                if result['code']=='REJECTED':
                    save(status='REJECTED', uncertain=None);raise Stop()
                setup['created'] = list(dict.fromkeys(setup.get('created', []) + ([field['name']] if result['code']=='CREATED' else [])))
                save(uncertain=None, created=setup['created'])
            fields = self.read_fields(value)
            ready = all(f['status']=='ready' for f in fields)
            save(fields=fields, status='PREPARED' if ready else 'WAITING')
            if ready:
                result = self.execute({'action':'revoke','url':value['url'],'token':token,'token_id':identity.get('token_id')}) if identity.get('token_id') else {'code':'UNCONFIRMED'}
                save(revocation='CONFIRMED' if result.get('code')=='CONFIRMED' else 'UNCONFIRMED')
        except Stop:
            pass
        except Exception:
            save(status='UNCERTAIN')
        finally:
            token = None
            payload.pop('setup_token', None)
            with self.store.locked():
                current = self.store.read()
                if current.get('preparation', {}).get('run_id') == run_id:
                    if current['preparation'].get('revocation') == 'NOT_ATTEMPTED':current['preparation']['revocation'] = 'UNCONFIRMED'
                    current['preparation']['local_secret'] = 'NOT_STORED'
                    self.store.write(current)
        return self.store.status()
