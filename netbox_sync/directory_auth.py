"""LDAPS settings and sessions inside the serialized auth transaction."""
import copy
import hashlib
import json
import secrets
import uuid
from .ldap_directory import DEFAULT, DirectoryError, validate
from .roles import READ, permissions, matrix

class DirectoryAuth:
    def settings(self):
        saved=self.state.get('ldap',{})
        return {'revision':saved.get('revision',0),'config':copy.deepcopy(saved.get('config',DEFAULT)),
                'bind_secret_present':bool(saved.get('secret_key')),'direct_groups_only':True,
                'read_revalidation_seconds':30,'roles':matrix()}

    def ldap_session(self, token, permission):
        from .auth_policy import AuthError, digest
        key=digest(token) if isinstance(token,str) else ''
        value=self.state.get('ldap_sessions',{}).get(key)
        saved=self.state.get('ldap',{})
        if (not value or value['expires']<=self.now or value['last_seen']+1800<=self.now
            or not saved.get('config',{}).get('enabled')):
            raise AuthError('AUTH_REQUIRED')
        principal=value['principal']
        if (value['checked']+30<=self.now or permission is not None and permission not in READ):
            try:
                checked=self.directory.call(saved['config'],self.auth_secrets.read(saved['secret_key']),
                    'refresh',username=principal['username'],expected_id=principal['identity'])
                if checked['role'] not in ('viewer','operator','admin') or checked['identity']!=principal['identity']:
                    raise DirectoryError('LDAP_ACCESS_DENIED')
            except Exception as exc:
                del self.state['ldap_sessions'][key]
                self.event('ldap.session.revoked',principal['id'])
                raise AuthError('AUTH_REQUIRED' if isinstance(exc,DirectoryError) and exc.code=='LDAP_ACCESS_DENIED' else 'AUTH_UNAVAILABLE') from None
            if principal['role']!=checked['role']:
                self.event('ldap.role.changed',principal['id'],previous_role=principal['role'],role=checked['role'])
            principal['role']=checked['role'];value['checked']=self.now
        if permission is not None and permission not in permissions(principal['role']):
            raise AuthError('AUTH_DENIED')
        value['last_seen']=self.now
        return principal

    def ldap_login(self, payload):
        from .auth_policy import AuthError, bounded, digest
        attempts=[v for v in self.state.get('ldap_attempts',[]) if v>self.now-300]
        if len(attempts)>=20: raise AuthError('AUTH_RATE_LIMITED')
        attempts.append(self.now);self.state['ldap_attempts']=attempts
        config=self.state.get('ldap',{})
        if not config.get('config',{}).get('enabled'): raise AuthError('AUTH_INVALID')
        username=bounded(payload.get('username'),128);password=bounded(payload.get('password'),256)
        try:
            user=self.directory.call(config['config'],self.auth_secrets.read(config['secret_key']),
                'login',username=username,password=password)
        except DirectoryError as exc:
            self.event('ldap.login.denied')
            raise AuthError('AUTH_INVALID' if exc.code=='LDAP_ACCESS_DENIED' else exc.code) from None
        except Exception: raise AuthError('AUTH_UNAVAILABLE') from None
        if user.get('role') not in ('viewer','operator','admin') or not isinstance(user.get('identity'),str):
            raise AuthError('AUTH_UNAVAILABLE')
        attempts.pop()  # Successful corporate logins do not consume the failure budget.
        actor=str(uuid.uuid5(uuid.UUID(config['directory_id']),user['identity']))
        principal=dict(id=actor,username=username,identity=user['identity'],role=user['role'],provider='ldap')
        sessions={k:v for k,v in self.state.get('ldap_sessions',{}).items() if v['expires']>self.now and v['last_seen']+1800>self.now}
        if len(sessions)>=256:
            del sessions[min(sessions,key=lambda k:sessions[k]['last_seen'])]
        token=secrets.token_urlsafe(32)
        sessions[digest(token)]=dict(principal=principal,issued=self.now,last_seen=self.now,
            expires=self.now+28800,checked=self.now)
        self.state['ldap_sessions']=sessions
        self.event('ldap.login',actor,role=principal['role'])
        return {'session':token,'max_age':28800}

    def recent(self, token):
        from .auth_policy import AuthError, digest
        value=self.state['sessions'].get(digest(token)) or self.state.get('ldap_sessions',{}).get(digest(token))
        if not value or value['issued']+900<=self.now: raise AuthError('AUTH_REQUIRED')

    def directory_action(self, action, payload, principal):
        from .auth_policy import AuthError, digest
        token=payload.get('session');self.session(token,'identity.manage')
        if action=='ldap.settings': return self.settings()
        if action=='roles': return {'roles':matrix()}
        self.recent(token)
        if action=='ldap.revoke':
            self.state['ldap_sessions']={}
            self.event('ldap.sessions.revoked',principal['id'])
            return {'revoked':True}
        local=self.state['principal']
        if not local or local.get('disabled'): raise AuthError('AUTH_DENIED')
        previous=self.state.get('ldap',{})
        if type(payload.get('expected_revision')) is not int or payload['expected_revision']!=previous.get('revision',0):
            raise AuthError('LDAP_CONFLICT')
        try: config=validate(payload.get('config'))
        except DirectoryError as exc: raise AuthError(exc.code) from None
        if action=='ldap.save' and not config['enabled'] and previous:
            self.state['ldap']={**previous,'config':{**previous['config'],'enabled':False},'revision':previous['revision']+1}
            self.state['ldap_sessions']={};self.state.pop('ldap_test',None)
            self.event('ldap.config.updated',principal['id'],revision=self.state['ldap']['revision'],enabled=False)
            return self.settings()
        password=payload.get('bind_password','')
        if not isinstance(password,str) or len(password)>4096 or '\x00' in password: raise AuthError('LDAP_INVALID')
        if not password:
            if (not previous.get('secret_key') or any(config[k]!=previous['config'][k] for k in ('host','port','bind_dn','ca_pem'))):
                # Never send an old credential to a changed endpoint/trust authority implicitly.
                raise AuthError('LDAP_INVALID')
            try: password=self.auth_secrets.read(previous['secret_key'])
            except Exception: raise AuthError('AUTH_UNAVAILABLE') from None
        proof=digest(json.dumps(config,sort_keys=True)+digest(password))
        if action=='ldap.test':
            try: self.directory.call(config,password,'test')
            except DirectoryError as exc: raise AuthError(exc.code) from None
            self.state['ldap_test']={'digest':proof,'actor':principal['id'],'expires':self.now+300}
            self.event('ldap.test',principal['id'])
            return {'ok':True,'expires_in':300,'direct_groups_only':True}
        if action!='ldap.save': raise AuthError('AUTH_DENIED')
        checked=self.state.get('ldap_test',{})
        # Disable is always possible for a recently authenticated administrator.
        if config['enabled'] and (checked.get('actor')!=principal['id'] or checked.get('digest')!=proof or checked.get('expires',0)<=self.now):
            raise AuthError('LDAP_INVALID')
        try: key=self.auth_secrets.create(password) if payload.get('bind_password') else previous['secret_key']
        except Exception: raise AuthError('AUTH_UNAVAILABLE') from None
        self.state['ldap']={'config':config,'secret_key':key,'revision':previous.get('revision',0)+1,
            'directory_id':previous.get('directory_id') or str(uuid.uuid4())}
        self.state['ldap_sessions']={};self.state.pop('ldap_test',None)
        self.event('ldap.config.updated',principal['id'],revision=self.state['ldap']['revision'],enabled=config['enabled'])
        return self.settings()
