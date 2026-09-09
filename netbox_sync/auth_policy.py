"""Server-owned local identity, sessions and onboarding destination policy.

No provider credentials, network requests, role assertions or environment reads.
Transactions are serialized by the store; failures are closed and safe to publish.
"""
from dataclasses import asdict
import hashlib
import ipaddress
import json
import re
import secrets
import time
import uuid

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError
from .api.egress import EgressPolicy, validate_host, LOCAL_NAMES

PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
PERMISSIONS = frozenset({
    'policy.read', 'policy.write', 'source.read', 'source.probe', 'source.register',
    'source.configure', 'source.schedule', 'source.plan', 'source.apply', 'source.remove',
    'run.read', 'diagnostics.read', 'bootstrap.manage', 'identity.manage',
})
CODES = frozenset({'AUTH_REQUIRED', 'AUTH_DENIED', 'AUTH_INVALID', 'AUTH_RATE_LIMITED',
    'AUTH_UNAVAILABLE', 'ENROLLMENT_INVALID', 'POLICY_CONFLICT', 'POLICY_INVALID',
    'POLICY_HOST_MANAGED', 'PROBE_RECEIPT_INVALID'})


class AuthError(RuntimeError):
    def __init__(self, code):
        self.code = code if code in CODES else 'AUTH_UNAVAILABLE'
        super().__init__(self.code)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def bounded(value, maximum=256):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise AuthError('AUTH_INVALID')
    return value


def initial_state():
    return {'principal': None, 'invitation': None, 'sessions': {}, 'attempts': [],
            'revision': 0, 'mode': 'legacy', 'ceiling': None, 'allowed_hosts': [],
            'denied_cidrs': [], 'changes': {}, 'receipts': {}}


class AuthPolicy:
    """Caller must hold the DB state row lock for the whole call, including hash work."""
    def __init__(self, state, baseline=None, clock=time.time):
        self.state = state
        self.baseline = baseline or EgressPolicy()
        self.now = clock()
        self.audit = []

    def event(self, action, actor=None, **details):
        self.audit.append({'action': action, 'actor': actor, 'at': self.now, **details})

    def root(self, action, payload):
        if action == 'status':
            return {'ready': True, 'enrolled': bool(self.state['principal'])}
        if action in ('invite', 'recover'):
            if action == 'invite' and self.state['principal']:
                raise AuthError('ENROLLMENT_INVALID')
            if action == 'recover' and not self.state['principal']:
                raise AuthError('ENROLLMENT_INVALID')
            token = secrets.token_urlsafe(32)
            self.state['invitation'] = {'hash': digest(token), 'expires': self.now + 900}
            if action == 'recover':
                self.state['attempts'] = []
                self.state['sessions'] = {}
                self.state['receipts'] = {}
                self.state['principal']['disabled'] = True
            self.event('root.' + action)
            return {'invitation': token, 'expires_in': 900}
        if action == 'managed':
            if payload.get('ceiling') not in ('existing', 'public-ipv4'):
                raise AuthError('POLICY_INVALID')
            # Public expansion requires explicit root approval; inherited deny survives.
            self.state.update(mode='managed', ceiling=payload['ceiling'],
                              revision=self.state['revision'] + 1)
            self.state['receipts'] = {}
            self.event('root.managed', ceiling=payload['ceiling'], revision=self.state['revision'])
            return {'revision': self.state['revision']}
        if action == 'revoke':
            self.state['sessions'] = {}
            self.state['receipts'] = {}
            self.event('root.revoke')
            return {'revoked': True}
        raise AuthError('AUTH_INVALID')

    def throttle(self):
        attempts = [at for at in self.state['attempts'] if at > self.now - 300]
        self.state['attempts'] = attempts
        if len(attempts) >= 5:
            raise AuthError('AUTH_RATE_LIMITED')
        attempts.append(self.now)

    def session(self, token, permission=None):
        value = self.state['sessions'].get(digest(token)) if isinstance(token, str) else None
        principal = self.state['principal']
        if (not value or not principal or principal.get('disabled')
                or value['expires'] <= self.now or value['last_seen'] + 1800 <= self.now):
            raise AuthError('AUTH_REQUIRED')
        if permission is not None and permission not in PERMISSIONS:
            raise AuthError('AUTH_DENIED')
        value['last_seen'] = self.now
        return principal

    def issue_session(self):
        self.state['sessions'] = {key: value for key, value in self.state['sessions'].items()
                                  if value['expires'] > self.now and value['last_seen'] + 1800 > self.now}
        if len(self.state['sessions']) >= 32:
            oldest = min(self.state['sessions'], key=lambda k: self.state['sessions'][k]['last_seen'])
            del self.state['sessions'][oldest]
        token = secrets.token_urlsafe(32)
        self.state['sessions'][digest(token)] = {'issued': self.now, 'last_seen': self.now,
                                                 'expires': self.now + 28800}
        return {'session': token, 'max_age': 28800}

    def effective(self):
        state = self.state
        if state['mode'] == 'legacy':
            return self.baseline
        denied = tuple(sorted(set((*self.baseline.denied_cidrs, *state['denied_cidrs']))))
        # A restrictive inherited ceiling stays authoritative. Exact host exceptions
        # can only widen a root-selected public IPv4 ceiling.
        if state['ceiling'] == 'existing':
            return EgressPolicy(**{**asdict(self.baseline), 'denied_cidrs': denied})
        return EgressPolicy(
            allowed_cidrs=self.baseline.allowed_cidrs or ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'),
            denied_cidrs=denied,
            allowed_hosts=tuple(sorted(set((*self.baseline.allowed_hosts, *state['allowed_hosts'])))),
            allowed_suffixes=self.baseline.allowed_suffixes)

    def policy(self):
        return {'revision': self.state['revision'], 'mode': self.state['mode'],
                'ceiling': self.state['ceiling'], 'allowed_hosts': self.state['allowed_hosts'],
                'denied_cidrs': self.state['denied_cidrs'], 'effective': asdict(self.effective())}

    def call(self, payload):
        action = payload.get('action')
        if action == 'enroll':
            self.throttle()
            invitation = self.state['invitation']
            token = bounded(payload.get('invitation'))
            username = bounded(payload.get('username'), 64)
            password = bounded(payload.get('password'), 256)
            if (not invitation or invitation['expires'] <= self.now
                    or not secrets.compare_digest(invitation['hash'], digest(token))):
                raise AuthError('ENROLLMENT_INVALID')
            if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.@-]{2,63}', username) or len(password) < 15:
                raise AuthError('AUTH_INVALID')
            principal = self.state['principal']
            self.state['principal'] = {'id': principal['id'] if principal else str(uuid.uuid4()),
                'username': username, 'password_hash': PASSWORDS.hash(password), 'disabled': False}
            self.state['invitation'] = None
            self.state['sessions'] = {}
            self.state['attempts'] = []
            self.event('enrolled', self.state['principal']['id'])
            return self.issue_session()
        if action == 'login':
            self.throttle()
            username = bounded(payload.get('username'), 64)
            password = bounded(payload.get('password'), 256)
            principal = self.state['principal']
            if not principal or principal.get('disabled'):
                # Equivalent expensive work prevents cheap username probing.
                PASSWORDS.hash(password)
                raise AuthError('AUTH_INVALID')
            try:
                valid = PASSWORDS.verify(principal['password_hash'], password)
            except (VerificationError, InvalidHashError):
                valid = False
            if not valid or not secrets.compare_digest(principal['username'].encode(), username.encode()):
                self.event('login.denied')
                raise AuthError('AUTH_INVALID')
            self.state['attempts'] = []
            self.event('login', principal['id'])
            return self.issue_session()
        token = payload.get('session')
        principal = self.session(token, payload.get('permission') if action == 'authorize' else None)
        actor = principal['id']
        if action == 'authorize':
            return {'principal_id': actor, 'username': principal['username'], 'permissions': sorted(PERMISSIONS)}
        if action == 'logout':
            self.state['sessions'].pop(digest(token), None)
            self.event('logout', actor)
            return {'logged_out': True}
        if action == 'policy':
            self.session(token, 'policy.read')
            return self.policy()
        if action == 'policy.update':
            self.session(token, 'policy.write')
            if self.state['sessions'][digest(token)]['issued'] + 900 <= self.now:
                raise AuthError('AUTH_REQUIRED')
            if self.state['mode'] != 'managed' or self.state['ceiling'] != 'public-ipv4':
                raise AuthError('POLICY_HOST_MANAGED')
            host = bounded(payload.get('host'), 253)
            try:
                host = validate_host(host)
                if host in LOCAL_NAMES or '.' not in host:
                    raise ValueError()
                try:
                    ip = ipaddress.ip_address(host)
                except ValueError:
                    ip = None
                if ip is not None and not ip.is_global:
                    raise ValueError()
            except ValueError:
                raise AuthError('POLICY_INVALID') from None
            key = bounded(payload.get('request_id'), 64)
            expected = payload.get('expected_revision')
            operation = payload.get('operation', 'allow')
            if operation not in ('allow', 'revoke'):
                raise AuthError('POLICY_INVALID')
            canonical = {'host': host, 'expected_revision': expected, 'operation': operation}
            previous = self.state['changes'].get(key)
            if previous:
                if previous['actor'] != actor or previous['request'] != canonical:
                    raise AuthError('POLICY_CONFLICT')
                return {'revision': previous['revision']}
            if type(expected) is not int or expected != self.state['revision']:
                raise AuthError('POLICY_CONFLICT')
            hosts = (sorted(set((*self.state['allowed_hosts'], host)))
                if operation == 'allow' else [value for value in self.state['allowed_hosts'] if value != host])
            # Leave room for inherited policy and the bounded 32 KiB RPC response.
            # Revocation remains possible at the host limit. Never commit an unreadable policy.
            if len(hosts) > 256 or len(json.dumps(hosts)) > 8192:
                raise AuthError('POLICY_INVALID')
            prior_hosts = self.state['allowed_hosts']
            self.state['allowed_hosts'] = hosts
            if len(json.dumps(self.policy()).encode()) > 24576:
                self.state['allowed_hosts'] = prior_hosts
                raise AuthError('POLICY_INVALID')
            self.state['revision'] += 1
            self.state['receipts'] = {}
            revision = self.state['revision']
            if len(self.state['changes']) >= 4096:
                oldest = min(self.state['changes'], key=lambda item: self.state['changes'][item]['revision'])
                del self.state['changes'][oldest]
            self.state['changes'][key] = {'actor': actor, 'request': canonical, 'revision': revision}
            self.event('policy.' + operation, actor, host=host, previous_revision=expected, revision=revision, request_id=key)
            return {'revision': revision}
        if action == 'probe.authorize':
            self.session(token, 'source.probe')
            if payload.get('revision') != self.state['revision']:
                raise AuthError('POLICY_CONFLICT')
            return {'principal_id': actor, **self.policy()}
        if action == 'receipt.issue':
            self.session(token, 'source.probe')
            if payload.get('revision') != self.state['revision']:
                raise AuthError('POLICY_CONFLICT')
            receipts = {k: v for k, v in self.state['receipts'].items() if v['expires'] > self.now}
            if len(receipts) >= 128:
                raise AuthError('AUTH_UNAVAILABLE')
            key = bounded(payload.get('receipt'))
            receipts[digest(key)] = {'actor': actor, 'revision': self.state['revision'],
                'destination': bounded(payload.get('destination'), 253),
                'provider': bounded(payload.get('provider'), 16), 'expires': self.now + 600}
            self.state['receipts'] = receipts
            return {'issued': True}
        if action in ('receipt.consume', 'receipt.cancel'):
            self.session(token, 'source.register')
            key = digest(bounded(payload.get('receipt')))
            value = self.state['receipts'].get(key)
            if action == 'receipt.cancel':
                if value and value['actor'] != actor:
                    raise AuthError('PROBE_RECEIPT_INVALID')
                if value:
                    value['consumed'] = True
                return {'consumed': True}
            if (not value or value['actor'] != actor or value['expires'] <= self.now
                    or value['revision'] != self.state['revision']):
                raise AuthError('PROBE_RECEIPT_INVALID')
            if action == 'receipt.consume' and (value['destination'] != payload.get('destination')
                                               or value['provider'] != payload.get('provider')):
                raise AuthError('PROBE_RECEIPT_INVALID')
            if action == 'receipt.consume' and value.get('consumed'):
                raise AuthError('PROBE_RECEIPT_INVALID')
            value['consumed'] = True
            return {'consumed': True}
        raise AuthError('AUTH_DENIED')
