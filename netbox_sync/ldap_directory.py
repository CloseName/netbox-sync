"""Bounded LDAPS adapter. Secrets only in memory/stdin, never argv/environment/logs."""
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

CODES = frozenset({'LDAP_INVALID', 'LDAP_TLS_FAILED', 'LDAP_UNAVAILABLE',
    'LDAP_BIND_FAILED', 'LDAP_ACCESS_DENIED', 'LDAP_CONFLICT'})

class DirectoryError(RuntimeError):
    def __init__(self, code):
        self.code = code if code in CODES else 'LDAP_UNAVAILABLE'
        super().__init__(self.code)

DEFAULT = dict(enabled=False, host='', port=636, bind_dn='', user_base='', group_base='',
    user_attribute='sAMAccountName', user_object_class='user', group_object_class='group',
    member_attribute='member', identity_attribute='objectGUID', account_control_attribute='userAccountControl',
    ca_pem='', mappings=[])

def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT):
        raise DirectoryError('LDAP_INVALID')
    if len(json.dumps(value).encode())>10000: raise DirectoryError('LDAP_INVALID')
    result = dict(value)
    if type(result['enabled']) is not bool or type(result['port']) is not int or not 1 <= result['port'] <= 65535:
        raise DirectoryError('LDAP_INVALID')
    for key, limit in (('host',253),('bind_dn',1024),('user_base',1024),('group_base',1024),('ca_pem',8192)):
        item=result[key]
        if not isinstance(item,str) or len(item)>limit or '\x00' in item:
            raise DirectoryError('LDAP_INVALID')
    # No URL, authority credentials, scheme override, referrals or implicit LDAP.
    if not re.fullmatch(r'(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',result['host']):
        raise DirectoryError('LDAP_INVALID')
    if any(not result[k].strip() for k in ('bind_dn','user_base','group_base')):
        raise DirectoryError('LDAP_INVALID')
    for key in ('user_attribute','user_object_class','group_object_class','member_attribute','identity_attribute','account_control_attribute'):
        if not isinstance(result[key],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{0,63}',result[key]):
            raise DirectoryError('LDAP_INVALID')
    mappings=result['mappings']
    if not isinstance(mappings,list) or not 1 <= len(mappings) <= 32:
        raise DirectoryError('LDAP_INVALID')
    seen=set()
    for mapping in mappings:
        if (not isinstance(mapping,dict) or set(mapping)!={'dn','role'} or mapping['role'] not in ('viewer','operator','admin')
            or not isinstance(mapping['dn'],str) or not 1 <= len(mapping['dn']) <= 1024
            or '\x00' in mapping['dn'] or mapping['dn'].strip().casefold() in seen):
            raise DirectoryError('LDAP_INVALID')
        seen.add(mapping['dn'].strip().casefold())
    try:
        ssl.create_default_context(cadata=result['ca_pem'] or None)
    except (ssl.SSLError, ValueError):
        raise DirectoryError('LDAP_INVALID') from None
    if 'PRIVATE KEY' in result['ca_pem']:
        raise DirectoryError('LDAP_INVALID')
    return result

class DirectoryClient:
    def call(self, config, secret, operation, **kwargs):
        payload=dict(config=config,secret=secret,operation=operation,**kwargs)
        try:
            child=subprocess.run([sys.executable,'-B','-m','netbox_sync.ldap_directory'],
                input=json.dumps(payload).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                timeout=8,env={k:v for k,v in os.environ.items() if k in ('PATH','PYTHONPATH','SYSTEMROOT')})
            if child.returncode or len(child.stdout)>8192:
                raise DirectoryError('LDAP_UNAVAILABLE')
            value=json.loads(child.stdout)
            if 'error' in value: raise DirectoryError(value['error'])
            return value['result']
        except DirectoryError: raise
        except Exception: raise DirectoryError('LDAP_UNAVAILABLE') from None

def execute(payload):
    import ldap3
    from ldap3.utils.conv import escape_filter_chars
    config=validate(payload['config'])
    secret=payload.get('secret')
    if not isinstance(secret,str) or not secret or len(secret)>4096:
        raise DirectoryError('LDAP_BIND_FAILED')
    # Explicit Python TLS verification provides an unambiguous safe certificate code.
    context=ssl.create_default_context(cadata=config['ca_pem'] or None)
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    with socket.create_connection((config['host'],config['port']),timeout=2) as raw:
        with context.wrap_socket(raw,server_hostname=config['host']): pass
    with tempfile.TemporaryDirectory(prefix='netbox-sync-ldap-') as directory:
        ca=Path(directory)/'ca.pem'
        if config['ca_pem']: ca.write_text(config['ca_pem']);ca.chmod(0o600)
        tls=ldap3.Tls(validate=ssl.CERT_REQUIRED,version=ssl.PROTOCOL_TLS_CLIENT,
            ca_certs_file=str(ca) if config['ca_pem'] else None,valid_names=[config['host']])
        server=ldap3.Server(config['host'],port=config['port'],use_ssl=True,tls=tls,connect_timeout=2,get_info=ldap3.NONE)
        def connection(dn,password):
            return ldap3.Connection(server,user=dn,password=password,authentication=ldap3.SIMPLE,
                auto_referrals=False,read_only=True,receive_timeout=2,raise_exceptions=False,
                check_names=False)
        bind=connection(config['bind_dn'],secret)
        try:
            if not bind.bind(): raise DirectoryError('LDAP_BIND_FAILED')
            def search(base,expression,attributes,scope=ldap3.SUBTREE,limit=100):
                bind.search(base,expression,search_scope=scope,attributes=attributes,size_limit=limit,time_limit=2)
                if bind.result.get('result')!=0 or any(r.get('type')!='searchResEntry' for r in bind.response):
                    raise DirectoryError('LDAP_ACCESS_DENIED')
                return list(bind.entries)
            if payload['operation']=='test':
                for base in (config['user_base'],config['group_base']):
                    if len(search(base,'(objectClass=*)',['objectClass'],ldap3.BASE,1))!=1:
                        raise DirectoryError('LDAP_ACCESS_DENIED')
                # Every configured mapping must refer to a readable, existing group.
                for mapping in config['mappings']:
                    if len(search(mapping['dn'],'(objectClass='+escape_filter_chars(config['group_object_class'])+')',['objectClass'],ldap3.BASE,1))!=1:
                        raise DirectoryError('LDAP_ACCESS_DENIED')
                return {'ok':True,'nested_groups':False}
            username=payload.get('username')
            if not isinstance(username,str) or not 1<=len(username)<=128 or '\x00' in username:
                raise DirectoryError('LDAP_ACCESS_DENIED')
            expression='(&(objectClass='+escape_filter_chars(config['user_object_class'])+')('+config['user_attribute']+'='+escape_filter_chars(username)+'))'
            attrs=[config['identity_attribute'],config['account_control_attribute'],'accountExpires','msDS-User-Account-Control-Computed','pwdLastSet']
            entries=search(config['user_base'],expression,attrs,limit=2)
            if len(entries)!=1: raise DirectoryError('LDAP_ACCESS_DENIED')
            entry=entries[0]
            rawattrs={k.casefold():v for k,v in entry.entry_raw_attributes.items()}
            identifiers=rawattrs.get(config['identity_attribute'].casefold(),[])
            flags=rawattrs.get(config['account_control_attribute'].casefold(),[])
            if len(identifiers)!=1 or not identifiers[0] or len(flags)!=1:
                raise DirectoryError('LDAP_ACCESS_DENIED')
            try:
                if int(flags[0]) & 2: raise DirectoryError('LDAP_ACCESS_DENIED')
                if int((rawattrs.get('msds-user-account-control-computed') or [b'0'])[0]) & (16 | 8388608):
                    raise DirectoryError('LDAP_ACCESS_DENIED')
                expiry=int((rawattrs.get('accountexpires') or [b'0'])[0])
                import time
                if expiry not in (0,9223372036854775807) and expiry/10000000-11644473600 <= time.time():
                    raise DirectoryError('LDAP_ACCESS_DENIED')
                if rawattrs.get('pwdlastset')==[b'0']: raise DirectoryError('LDAP_ACCESS_DENIED')
            except (ValueError,TypeError): raise DirectoryError('LDAP_ACCESS_DENIED') from None
            identifier=identifiers[0].hex()
            if payload.get('expected_id') and payload['expected_id']!=identifier:
                raise DirectoryError('LDAP_ACCESS_DENIED')
            groups=search(config['group_base'],'(&(objectClass='+escape_filter_chars(config['group_object_class'])+')('+config['member_attribute']+'='+escape_filter_chars(entry.entry_dn)+'))',['objectClass'])
            dns={group.entry_dn.strip().casefold() for group in groups}
            roles={mapping['role'] for mapping in config['mappings'] if mapping['dn'].strip().casefold() in dns}
            if not roles: raise DirectoryError('LDAP_ACCESS_DENIED')
            if payload['operation']=='login':
                password=payload.get('password')
                if not isinstance(password,str) or not password or len(password)>256: raise DirectoryError('LDAP_ACCESS_DENIED')
                user=connection(entry.entry_dn,password)
                try:
                    if not user.bind(): raise DirectoryError('LDAP_ACCESS_DENIED')
                finally: user.unbind()
            elif payload['operation']!='refresh': raise DirectoryError('LDAP_INVALID')
            role=next(value for value in ('admin','operator','viewer') if value in roles)
            return {'identity':identifier,'role':role}
        finally: bind.unbind()

if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(32769)
        if len(raw)>32768: raise DirectoryError('LDAP_INVALID')
        result={'result':execute(json.loads(raw))}
    except ssl.SSLCertVerificationError: result={'error':'LDAP_TLS_FAILED'}
    except DirectoryError as exc: result={'error':exc.code}
    except Exception: result={'error':'LDAP_UNAVAILABLE'}
    print(json.dumps(result))
