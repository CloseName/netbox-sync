"""Individual directory roles and atomic membership snapshots in the auth row transaction."""
import copy
import uuid
from .ldap_directory import DirectoryError

SYNC_SECONDS = 300

class DirectoryUsers:
    def migrate_directory(self):
        saved=self.state.get('ldap')
        if not saved or saved.get('user_model')==2: return
        config=copy.deepcopy(saved['config'])
        mappings=config.pop('mappings',[])
        if 'group_dn' not in config:
            config['group_dn']=mappings[0]['dn'] if len(mappings)==1 else ''
            if len(mappings)!=1: config['enabled']=False
        saved.update(config=config,user_model=2,revision=saved.get('revision',0)+1)
        self.state['ldap_users']={}
        self.state['ldap_sessions']={}
        self.state.pop('ldap_test',None)
        self.state['ldap_user_revision']=0
        self.event('ldap.individual_roles.migrated',enabled=config['enabled'])

    def directory_user(self, value):
        if (not isinstance(value,dict) or not isinstance(value.get('identity'),str)
            or not 1<=len(value['identity'])<=128 or type(value.get('active')) is not bool
            or not isinstance(value.get('username'),str) or not 1<=len(value['username'])<=128
            or not isinstance(value.get('display_name'),str) or len(value['display_name'])>256):
            raise DirectoryError('LDAP_UNAVAILABLE')
        identity=value['identity']
        previous=self.state.get('ldap_users',{}).get(identity,{})
        return {'id':str(uuid.uuid5(uuid.UUID(self.state['ldap']['directory_id']),identity)),
            'identity':identity,'username':value['username'],'display_name':value['display_name'],
            'role':previous.get('role','viewer'),'active':value['active'],
            'access_state':'allowed' if value['active'] else 'disabled'}

    def sync_directory(self, *, due=False):
        from .auth_policy import AuthError
        saved=self.state.get('ldap',{})
        if not saved.get('config',{}).get('enabled'): return {'skipped':True}
        sync=self.state.setdefault('ldap_sync',{})
        if due and sync.get('attempted_at',0)+SYNC_SECONDS>self.now: return {'skipped':True}
        sync['attempted_at']=self.now
        try:
            result=self.directory.call(saved['config'],self.auth_secrets.read(saved['secret_key']),'sync')
            if result.get('complete') is not True or not isinstance(result.get('users'),list) or len(result['users'])>5000:
                raise DirectoryError('LDAP_UNAVAILABLE')
            next_users={}
            for value in result['users']:
                row=self.directory_user(value)
                if row['identity'] in next_users: raise DirectoryError('LDAP_UNAVAILABLE')
                next_users[row['identity']]=row
            for identity,previous in self.state.get('ldap_users',{}).items():
                if identity not in next_users: next_users[identity]={**previous,'active':False,'access_state':'not_member'}
            if len(next_users)>10000: raise DirectoryError('LDAP_UNAVAILABLE')
        except Exception as exc:
            sync['error']=exc.code if isinstance(exc,DirectoryError) else 'LDAP_UNAVAILABLE'
            self.event('ldap.users.sync_failed',code=sync['error'])
            raise AuthError(sync['error']) from None
        self.state['ldap_users']=next_users
        self.state['ldap_user_revision']=self.state.get('ldap_user_revision',0)+1
        sync.update(success_at=self.now,error=None)
        self.state['ldap_sessions']={key:session for key,session in self.state.get('ldap_sessions',{}).items()
            if next_users.get(session['principal']['identity'],{}).get('active')}
        self.event('ldap.users.synced',count=len(result['users']))
        return {'synced':True,'count':len(result['users'])}

    def users_action(self, action, payload, principal):
        from .auth_policy import AuthError
        self.session(payload.get('session'),'identity.manage')
        if action=='ldap.users.sync':
            self.recent(payload.get('session'))
            return self.sync_directory()
        if action=='ldap.users.role':
            self.recent(payload.get('session'))
            local=self.state.get('principal')
            # The local emergency administrator is mandatory and cannot be edited here.
            if not local or local.get('disabled'): raise AuthError('AUTH_DENIED')
            if type(payload.get('revision')) is not int or payload['revision']!=self.state.get('ldap_user_revision',0): raise AuthError('LDAP_CONFLICT')
            row=next((u for u in self.state.get('ldap_users',{}).values() if u['id']==payload.get('id')),None)
            if not row or payload.get('role') not in ('viewer','operator','admin'): raise AuthError('LDAP_INVALID')
            previous=row['role'];row['role']=payload['role']
            self.state['ldap_user_revision']=self.state.get('ldap_user_revision',0)+1
            self.state['ldap_sessions']={k:v for k,v in self.state.get('ldap_sessions',{}).items() if v['principal']['identity']!=row['identity']}
            self.event('ldap.user.role_changed',principal['id'],user_id=row['id'],previous_role=previous,role=row['role'])
            return {'updated':True}
        query=payload.get('q','');offset=payload.get('offset',0)
        if not isinstance(query,str) or len(query)>128 or type(offset) is not int or not 0<=offset<=10000: raise AuthError('LDAP_INVALID')
        rows=sorted((u for u in self.state.get('ldap_users',{}).values() if query.casefold() in (u['username']+' '+u['display_name']).casefold()),key=lambda u:(u['username'].casefold(),u['id']))
        return {'users':[{k:v for k,v in row.items() if k!='identity'} for row in rows[offset:offset+10]],
            'total':len(rows),'offset':offset,'revision':self.state.get('ldap_user_revision',0),
            'sync':copy.deepcopy(self.state.get('ldap_sync',{})),'sync_interval_seconds':SYNC_SECONDS,
            'enabled':bool(self.state.get('ldap',{}).get('config',{}).get('enabled'))}
